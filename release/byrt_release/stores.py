"""Builds and everything that talks to a store.

Every command goes through a Runner, so tests can record calls without running anything. The
contents of the key files are never read here: commands get the key as a file path plus the key id
and issuer id, through environment variables, or as flags where the tool takes nothing else.
"""
import json
import os
import plistlib
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from byrt_release.config import Config
from byrt_release.project import Kind, Project, ReleaseError

TOOL_DIR = Path(__file__).resolve().parent.parent

Runner = Callable[[list[str], Path, dict[str, str]], str]

# The Kotlin CLI can report an error, plain or inside a diagnostic box, and still exit 0. The rule
# is for that CLI only: applied to an upload command it could call a finished upload failed.
_KOTLIN_ERROR_LINE = re.compile(r"^\W*ERROR:")

_QUIET_KOTLIN = {"KOTLIN_CLI_NO_WELCOME_BANNER": "1"}
_QUIET_FASTLANE = {"FASTLANE_SKIP_UPDATE_CHECK": "1", "FASTLANE_HIDE_CHANGELOG": "1"}


def run(argv: list[str], cwd: Path, env: dict[str, str]) -> str:
    """Run a command, show its output as it comes, and return it. Raises when the command failed."""
    command = " ".join(argv)
    lines = []
    with subprocess.Popen(
        argv, cwd=cwd, env={**os.environ, **env}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    ) as process:
        for line in process.stdout:
            print(line, end="", flush=True)
            lines.append(line)
    exit_code = process.returncode
    if exit_code != 0:
        raise ReleaseError(f"`{command}` failed with exit code {exit_code}")
    if Path(argv[0]).name == "kotlin":
        for line in lines:
            if _KOTLIN_ERROR_LINE.match(line):
                raise ReleaseError(f"`{command}` exited 0 but reported: {line.strip()}")
    return "".join(lines)


@dataclass(frozen=True)
class StoreState:
    android_code: int | None
    ios_build: int | None
    ios_live_name: str | None


def store_state(project: Project, config: Config, run: Runner) -> StoreState:
    """The highest build numbers the stores have seen and the App Store version that is live."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "state.json"
        _lane(run, "store_state", {**_app_ids(project), "out": str(out)}, _store_env(project, config))
        data = json.loads(out.read_text())
    return StoreState(data.get("android_code"), data.get("ios_build"), data.get("ios_live_name"))


def fetch_listing(project: Project, config: Config, run: Runner) -> None:
    """Create one locale folder per store language under metadata/, holding the live what's-new text."""
    options = {
        **_app_ids(project),
        "ios_dir": str(project.root / "metadata" / "ios"),
        "android_dir": str(project.root / "metadata" / "android"),
    }
    _lane(run, "fetch_listing", options, _store_env(project, config))


def build_android(project: Project, run: Runner) -> Path:
    if project.kind is Kind.TOOLCHAIN:
        output = run(["./kotlin", "package", "-m", "androidApp"], project.root, _QUIET_KOTLIN)
        printed = re.search(r"^Package created at: (.+\.aab)\s*$", output, flags=re.MULTILINE)
        aab = Path(printed.group(1)) if printed else None
    else:
        run(["./gradlew", ":app:bundleRelease"], project.root, {})
        aab = project.root / "app/build/outputs/bundle/release/app-release.aab"
    if aab is None or not aab.is_file():
        raise ReleaseError("the build finished but produced no Android bundle (.aab)")
    # A rebuild with nothing changed leaves the bundle alone, so its age is judged against the
    # version bump, not against this run.
    if aab.stat().st_mtime < project.android.version_file.stat().st_mtime:
        raise ReleaseError(f"{aab} is older than the version bump; the build did not write a new bundle")
    return aab


def publish_ios(project: Project, config: Config, run: Runner) -> None:
    """Build the iOS app and upload it to TestFlight."""
    if project.kind is Kind.TOOLCHAIN:
        env = {**_asc_env(config), **_QUIET_KOTLIN}
        run(["./kotlin", "publish", "testflight", "-m", "iosApp"], project.root, env)
        return
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "app.xcarchive"
        options = Path(tmp) / "ExportOptions.plist"
        with options.open("wb") as file:
            plistlib.dump(
                {
                    "method": "app-store-connect",
                    "destination": "upload",
                    "signingStyle": "automatic",
                    "teamID": project.ios.team_id,
                },
                file,
            )
        # xcodebuild takes the key only as flags, and it echoes its arguments, so the key id and
        # issuer id show up in its output. The key file itself is passed as a path.
        signing = [
            "-allowProvisioningUpdates",
            "-authenticationKeyPath", str(config.asc_key_path),
            "-authenticationKeyID", config.asc_key_id,
            "-authenticationKeyIssuerID", config.asc_issuer_id,
        ]  # fmt: skip
        run(
            [
                "xcodebuild",
                "-project", str(project.ios.xcodeproj),
                "-scheme", project.ios.xcodeproj.stem,
                "-configuration", "Release",
                "-destination", "generic/platform=iOS",
                "-archivePath", str(archive),
                "archive",
                *signing,
            ],
            project.root,
            {},
        )  # fmt: skip
        run(
            [
                "xcodebuild",
                "-exportArchive",
                "-archivePath", str(archive),
                "-exportOptionsPlist", str(options),
                "-exportPath", str(Path(tmp) / "export"),
                *signing,
            ],
            project.root,
            {},
        )  # fmt: skip


def upload_android(project: Project, aab: Path, config: Config, run: Runner) -> None:
    """Upload the bundle and the what's-new texts to the Play internal testing track."""
    options = {
        "package_name": project.android.application_id,
        "aab": str(aab),
        "metadata_path": str(project.root / "metadata" / "android"),
    }
    _lane(run, "upload_android", options, _play_env(config))


def upload_ios_notes(project: Project, version_name: str, config: Config, run: Runner) -> None:
    """Put the what's-new texts on the App Store version, creating it if needed. Submits nothing."""
    options = {
        "bundle_id": project.ios.bundle_id,
        "app_version": version_name,
        "metadata_path": str(project.root / "metadata" / "ios"),
    }
    _lane(run, "upload_ios_notes", options, _asc_env(config))


def _lane(run: Runner, lane: str, options: dict[str, str], env: dict[str, str]) -> None:
    arguments = [f"{key}:{value}" for key, value in options.items()]
    run(["fastlane", lane, *arguments], TOOL_DIR, {**env, **_QUIET_FASTLANE})


def _app_ids(project: Project) -> dict[str, str]:
    ids = {}
    if project.ios:
        ids["bundle_id"] = project.ios.bundle_id
    if project.android:
        ids["package_name"] = project.android.application_id
    return ids


def _store_env(project: Project, config: Config) -> dict[str, str]:
    return {**(_asc_env(config) if project.ios else {}), **(_play_env(config) if project.android else {})}


def _asc_env(config: Config) -> dict[str, str]:
    return {
        "KOTLIN_TOOLCHAIN_ASC_KEY_PATH": str(config.asc_key_path),
        "KOTLIN_TOOLCHAIN_ASC_KEY_ID": config.asc_key_id,
        "KOTLIN_TOOLCHAIN_ASC_KEY_ISSUER_ID": config.asc_issuer_id,
    }


def _play_env(config: Config) -> dict[str, str]:
    return {"SUPPLY_JSON_KEY": str(config.play_json_key)}

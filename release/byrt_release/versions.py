"""Read, raise and write version names and build numbers in the four file formats."""
import re
from dataclasses import dataclass
from pathlib import Path

from byrt_release.project import AndroidTarget, IosTarget, ReleaseError


@dataclass(frozen=True)
class Version:
    name: str
    build: int


# Per file suffix: (name pattern, build pattern). Group 2 is the value; groups 1 and 3 are kept as they are.
_PATTERNS = {
    ".yaml": (r'^(\s*versionName:\s*"?)([^"\n]+?)("?\s*)$', r"^(\s*versionCode:\s*)(\d+)(\s*)$"),
    ".kts": (r'(versionName\s*=\s*")([^"]+)(")', r"(versionCode\s*=\s*)(\d+)()"),
    ".plist": (
        r"(<key>CFBundleShortVersionString</key>\s*<string>)([^<]*)(</string>)",
        r"(<key>CFBundleVersion</key>\s*<string>)([^<]*)(</string>)",
    ),
    ".pbxproj": (r'(MARKETING_VERSION = "?)([^";]+)("?;)', r'(CURRENT_PROJECT_VERSION = "?)([^";]+)("?;)'),
}


def read_android(target: AndroidTarget) -> Version:
    return _read(target.version_file, target.version_file)


def write_android(target: AndroidTarget, version: Version) -> None:
    _write(target.version_file, target.version_file, version)


def read_ios(target: IosTarget) -> Version:
    return _read(target.name_file, target.build_file)


def write_ios(target: IosTarget, version: Version) -> None:
    _write(target.name_file, target.build_file, version)


def bump_name(name: str) -> str:
    parts = _numbers(name)
    return ".".join(str(part) for part in (*parts[:-1], parts[-1] + 1))


def next_version(
    repo: Version, store_build: int | None, store_live_name: str | None, name_override: str | None
) -> Version:
    """The version to release: one build above the highest the repo or the store knows."""
    name = name_override or bump_name(repo.name)
    if store_live_name is not None and _numbers(name) <= _numbers(store_live_name):
        raise ReleaseError(f"new version {name} is not above {store_live_name}, the version live in the store")
    _numbers(name)
    return Version(name, max(repo.build, store_build or 0) + 1)


def _numbers(name: str) -> tuple[int, ...]:
    if not re.fullmatch(r"\d+(\.\d+)*", name):
        raise ReleaseError(f"version name {name!r} is not dotted numbers; give the new name explicitly")
    return tuple(int(part) for part in name.split("."))


def _read(name_file: Path, build_file: Path) -> Version:
    name = _value(name_file, _PATTERNS[name_file.suffix][0])
    build = _value(build_file, _PATTERNS[build_file.suffix][1])
    if not build.isdigit():
        raise ReleaseError(f"{build_file}: build number {build!r} is not a whole number")
    return Version(name, int(build))


def _write(name_file: Path, build_file: Path, version: Version) -> None:
    _replace(name_file, _PATTERNS[name_file.suffix][0], version.name)
    _replace(build_file, _PATTERNS[build_file.suffix][1], str(version.build))


def _value(path: Path, pattern: str) -> str:
    values = {match[1] for match in re.findall(pattern, path.read_text(), flags=re.MULTILINE)}
    if len(values) != 1:
        found = ", ".join(sorted(values)) or "nothing"
        raise ReleaseError(f"{path}: expected one version value, found {found}")
    return values.pop()


def _replace(path: Path, pattern: str, value: str) -> None:
    text, count = re.subn(
        pattern, lambda match: match[1] + value + match[3], path.read_text(), flags=re.MULTILINE
    )
    if count == 0:
        raise ReleaseError(f"{path}: found no version value to update")
    path.write_text(text)

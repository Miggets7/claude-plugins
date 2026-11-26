"""The `release` command: prepare a release, let a person read the text, then ship it."""
import argparse
import hashlib
import sys
from pathlib import Path

from byrt_release import gitops, notes, state, stores
from byrt_release.config import Config, load_config
from byrt_release.notes import Ask
from byrt_release.project import Project, ReleaseError, detect
from byrt_release.state import State
from byrt_release.stores import Runner
from byrt_release.versions import Version, next_version, read_android, read_ios, write_android, write_ios

PLATFORM_NAMES = {"android": "Android", "ios": "iOS"}


def platforms_to_release(project: Project, only: str | None) -> list[str]:
    available = [name for name in ("android", "ios") if getattr(project, name) is not None]
    if only is None:
        return available
    if only not in available:
        raise ReleaseError(f"this repo has no {only} app")
    return [only]


def init(root: Path, config: Config, run: Runner) -> None:
    """Fetch the store languages and live what's-new texts into metadata/, once per app."""
    project = detect(root)
    stores.fetch_listing(project, config, run)
    metadata = root / "metadata"
    source = root / notes.SOURCE
    english_files = [
        *sorted(metadata.glob("ios/en*/release_notes.txt")),
        *sorted(metadata.glob("android/en*/changelogs/*.txt"), reverse=True),
    ]
    english = next((file.read_text().strip() for file in english_files if file.read_text().strip()), None)
    if not source.exists() and english:
        source.write_text(english + "\n")
    for platform in ("ios", "android"):
        folder = metadata / platform
        locales = sorted(entry.name for entry in folder.iterdir() if entry.is_dir()) if folder.is_dir() else []
        if locales:
            print(f"{PLATFORM_NAMES[platform]} store languages: {', '.join(locales)}")
    print("Commit the metadata/ folder; `release prepare` writes its texts there.")


def prepare(
    root: Path,
    config: Config,
    run: Runner,
    ask: Ask,
    only: str | None,
    android_version: str | None,
    ios_version: str | None,
    since: str | None,
) -> None:
    """Raise the versions and write the what's-new texts. Commits nothing."""
    if state.load(root) is not None:
        raise ReleaseError("a release is already prepared here; run `release ship` or `release abort`")
    project = detect(root)
    platforms = platforms_to_release(project, only)
    head = gitops.preflight(root)

    bases = set()
    for platform in platforms:
        base = since or gitops.previous_tag(root, platform)
        if base is None:
            raise ReleaseError(
                f"no earlier {platform} release tag in this repo; "
                "pass --since <commit or tag of the last store release>"
            )
        bases.add(base)
    commits = gitops.commits_since(root, sorted(bases))
    if not commits:
        raise ReleaseError(f"nothing to release: no commits since {', '.join(sorted(bases))}")

    store = stores.store_state(project, config, run)
    current: dict[str, Version] = {}
    versions: dict[str, Version] = {}
    if "android" in platforms:
        current["android"] = read_android(project.android)
        versions["android"] = next_version(current["android"], store.android_code, None, android_version)
    if "ios" in platforms:
        current["ios"] = read_ios(project.ios)
        versions["ios"] = next_version(current["ios"], store.ios_build, store.ios_live_name, ios_version)

    targets = notes.targets(project, versions)
    touched = {notes.SOURCE, *targets, *_version_files(project, platforms)}
    try:
        reference = notes.tone_reference(root)
        english = notes.draft(commits, reference, platforms, ask)
        texts = notes.translate(english, {locale for locale, _ in targets.values()}, ask)
        if "android" in versions:
            write_android(project.android, versions["android"])
        if "ios" in versions:
            write_ios(project.ios, versions["ios"])
        notes.write_all(root, english, texts, targets)
    except BaseException:
        gitops.restore(root, touched)
        raise
    state.save(
        root,
        State(
            head=head,
            previous=current,
            platforms=versions,
            touched=sorted(str(path) for path in touched),
            english_sha256=_sha256(english),
            done=[],
        ),
    )

    for platform in platforms:
        old, new = current[platform], versions[platform]
        print(f"{PLATFORM_NAMES[platform]}: {old.name} ({old.build}) -> {new.name} ({new.build})")
    print("\nChanged files:")
    for path in sorted(touched):
        print(f"  {path}")
    print(f"\nWhat's new ({notes.SOURCE}):\n\n{english}\n")
    notes.validate(root, targets)
    print("Edit the text if needed (then run `release translate`), and run `release ship` to upload.")


def translate(root: Path, ask: Ask) -> None:
    """Redo the translations after metadata/whats_new.txt was edited."""
    prepared = _prepared(root)
    # The TestFlight upload carries no text, so only these steps have sent it to a store.
    if "android_upload" in prepared.done or "ios_notes" in prepared.done:
        raise ReleaseError(
            "a store already has these texts; finish with `release ship`, or run `release abort` "
            "and `release prepare` to release new ones"
        )
    targets = notes.targets(detect(root), prepared.platforms)
    english = notes.read_source(root)
    texts = notes.translate(english, {locale for locale, _ in targets.values()}, ask)
    notes.write_all(root, english, texts, targets)
    prepared.english_sha256 = _sha256(english)
    state.save(root, prepared)
    notes.validate(root, targets)
    print(f"Translated into {len(targets)} store files. Run `release ship` to upload.")


def abort(root: Path) -> None:
    """Put back the files `prepare` changed and forget the prepared release."""
    prepared = _prepared(root)
    if "commit" in prepared.done:
        raise ReleaseError("the release commit already exists; run `release ship` to finish pushing it")
    uploaded = [step for step in ("android_upload", "ios_publish") if step in prepared.done]
    project = detect(root)
    # Version files also hold settings a person may have edited since, so only the numbers go back.
    if "android" in prepared.previous:
        write_android(project.android, prepared.previous["android"])
    if "ios" in prepared.previous:
        write_ios(project.ios, prepared.previous["ios"])
    texts = {Path(path) for path in prepared.touched} - _version_files(project, list(prepared.previous))
    gitops.restore(root, texts)
    state.clear(root)
    print("Release aborted; the version numbers and texts are back to the last commit.")
    if uploaded:
        print("A build was already uploaded. Its number is used up; the next `prepare` takes the next one.")


def ship(root: Path, config: Config, run: Runner, dry_run: bool) -> None:
    """Build, upload to TestFlight and the Play internal track, then commit, tag and push."""
    prepared = _prepared(root)
    project = detect(root)
    versions = prepared.platforms
    touched = {Path(path) for path in prepared.touched}
    done = prepared.done

    if "commit" not in done:
        if gitops.head(root) != prepared.head:
            raise ReleaseError(
                "new commits arrived since `release prepare`; run `release abort`, then `release prepare` again"
            )
        # The push at the end would be rejected after both uploads, with nothing left to undo it.
        if gitops.remote_head(root) != prepared.head:
            raise ReleaseError(
                "origin has new commits since `release prepare`; run `release abort`, pull, "
                "then `release prepare` again"
            )
        unrelated = gitops.changed_paths(root) - touched
        if unrelated:
            listing = ", ".join(sorted(str(path) for path in unrelated))
            raise ReleaseError(f"files changed that are not part of the release: {listing}")
        on_disk = {
            **({"android": read_android(project.android)} if "android" in versions else {}),
            **({"ios": read_ios(project.ios)} if "ios" in versions else {}),
        }
        for name, version in versions.items():
            if on_disk[name] != version:
                found = on_disk[name]
                raise ReleaseError(
                    f"the {PLATFORM_NAMES[name]} version file holds {found.name} ({found.build}), not the "
                    f"prepared {version.name} ({version.build}); run `release abort`, then `release prepare` again"
                )
        if _sha256(notes.read_source(root)) != prepared.english_sha256:
            raise ReleaseError(f"{notes.SOURCE} changed since the translations were made; run `release translate`")
        notes.validate(root, notes.targets(project, versions))

    labels = [f"{PLATFORM_NAMES[name]} {version.name} ({version.build})" for name, version in versions.items()]
    message = "Release " + " and ".join(labels)
    tags = [f"{name}-{version.name}-{version.build}" for name, version in versions.items()]
    aab: Path | None = None

    def android_build() -> None:
        nonlocal aab
        aab = stores.build_android(project, run)

    steps = {
        "android_build": ("build the Android bundle", android_build),
        "ios_publish": (
            "build the iOS app and upload it to TestFlight",
            lambda: stores.publish_ios(project, config, run),
        ),
        "android_upload": (
            "upload the bundle and its texts to the Play internal testing track",
            lambda: stores.upload_android(project, aab, config, run),
        ),
        "ios_notes": (
            f"put the texts on App Store version {versions['ios'].name if 'ios' in versions else ''} (not submitted)",
            lambda: stores.upload_ios_notes(project, versions["ios"].name, config, run),
        ),
        "commit": (f'commit "{message}"', lambda: gitops.commit(root, touched, message)),
        "tag": (f"tag {', '.join(tags)}", lambda: [gitops.tag(root, name) for name in tags]),
        "push": ("push the commit and tags", lambda: gitops.push(root, tags)),
    }
    order = [
        *(["android_build"] if "android" in versions else []),
        *(["ios_publish"] if "ios" in versions else []),
        *(["android_upload"] if "android" in versions else []),
        *(["ios_notes"] if "ios" in versions else []),
        "commit",
        "tag",
        "push",
    ]
    # The bundle is not kept between runs, so it is built again while its upload is still open.
    pending = [
        step
        for step in order
        if step not in done or (step == "android_build" and "android_upload" not in done)
    ]

    if dry_run:
        print("Checks passed. `release ship` would:")
        for number, step in enumerate(pending, start=1):
            print(f"  {number}. {steps[step][0]}")
        return

    for step in pending:
        print(f"\n==> {steps[step][0]}", flush=True)
        steps[step][1]()
        if step not in done:
            done.append(step)
            state.save(root, prepared)
    state.clear(root)
    print(f"\nDone: {message}.")
    print("Promote the build in App Store Connect and the Play Console when you want it live.")


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="release", description="Release the app in this repo to the stores.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="once per app: fetch store languages and live texts into metadata/")
    prepare_parser = commands.add_parser("prepare", help="raise versions and draft the what's-new texts")
    prepare_parser.add_argument("--only", choices=["android", "ios"], help="release one platform")
    prepare_parser.add_argument("--android-version", metavar="X", help="Android version name to use")
    prepare_parser.add_argument("--ios-version", metavar="X", help="iOS version to use")
    prepare_parser.add_argument("--since", metavar="REF", help="commit or tag of the last store release")
    commands.add_parser("translate", help="redo translations after editing metadata/whats_new.txt")
    ship_parser = commands.add_parser("ship", help="build, upload, then commit, tag and push")
    ship_parser.add_argument("--dry-run", action="store_true", help="run the checks and list the steps only")
    commands.add_parser("abort", help="undo `prepare`")
    args = parser.parse_args(argv)
    root = root or Path.cwd()

    try:
        if args.command == "init":
            init(root, load_config(), stores.run)
        elif args.command == "prepare":
            prepare(
                root,
                load_config(),
                stores.run,
                notes.ask_claude,
                args.only,
                args.android_version,
                args.ios_version,
                args.since,
            )
        elif args.command == "translate":
            translate(root, notes.ask_claude)
        elif args.command == "ship":
            ship(root, load_config(), stores.run, args.dry_run)
        elif args.command == "abort":
            abort(root)
    except ReleaseError as error:
        print(f"release: {error}", file=sys.stderr)
        return 1
    return 0


def _prepared(root: Path) -> State:
    prepared = state.load(root)
    if prepared is None:
        raise ReleaseError("no release is prepared in this repo; run `release prepare` first")
    return prepared


def _version_files(project: Project, platforms: list[str]) -> set[Path]:
    files = set()
    if "android" in platforms:
        files.add(project.android.version_file)
    if "ios" in platforms:
        files.update({project.ios.name_file, project.ios.build_file})
    return {file.relative_to(project.root) for file in files}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

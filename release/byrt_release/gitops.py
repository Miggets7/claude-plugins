"""Git checks and actions around a release. Runs git directly; nothing here talks to a store."""
import subprocess
from pathlib import Path

from byrt_release.project import ReleaseError


def preflight(root: Path) -> str:
    """Return HEAD when the tree is clean and the default branch equals its remote; otherwise explain."""
    changed = changed_paths(root)
    if changed:
        listing = ", ".join(sorted(str(path) for path in changed))
        raise ReleaseError(f"uncommitted or untracked files: {listing}. Commit, stash or remove them first.")
    branch = default_branch(root)
    current = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if current != branch:
        raise ReleaseError(f"on branch {current}; releases are cut from {branch}")
    head = _git(root, "rev-parse", "HEAD")
    if head != remote_head(root):
        raise ReleaseError(f"{branch} differs from origin/{branch}; pull or push first")
    return head


def default_branch(root: Path) -> str:
    ref = _git(
        root,
        "symbolic-ref",
        "--short",
        "refs/remotes/origin/HEAD",
        hint="run `git remote set-head origin --auto` once in this repo",
    )
    return ref.removeprefix("origin/")


def head(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD")


def remote_head(root: Path) -> str:
    """Fetch the default branch and return the commit origin has for it."""
    branch = default_branch(root)
    _git(root, "fetch", "--quiet", "origin", branch)
    return _git(root, "rev-parse", f"origin/{branch}")


def previous_tag(root: Path, platform: str) -> str | None:
    result = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0", "--match", f"{platform}-*"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def commits_since(root: Path, bases: list[str]) -> list[str]:
    """Messages of the non-merge commits after each base, each commit once."""
    messages: dict[str, str] = {}
    for base in bases:
        log = _git(root, "log", "--no-merges", "--format=%H%x1f%B%x1e", f"{base}..HEAD")
        for entry in filter(None, (chunk.strip() for chunk in log.split("\x1e"))):
            sha, message = entry.split("\x1f", 1)
            messages.setdefault(sha, message.strip())
    return list(messages.values())


def changed_paths(root: Path) -> set[Path]:
    output = _git(root, "status", "--porcelain", "-z", "--untracked-files=all", strip=False)
    entries = [entry for entry in output.split("\0") if entry]
    paths: set[Path] = set()
    index = 0
    while index < len(entries):
        status, path = entries[index][:2], entries[index][3:]
        paths.add(Path(path))
        if status[0] in "RC":  # a rename or copy is followed by its source path
            index += 1
            paths.add(Path(entries[index]))
        index += 1
    return paths


def restore(root: Path, paths: set[Path]) -> None:
    """Bring the given paths back to HEAD: tracked files are reverted, new files are deleted."""
    for path in paths:
        tracked = subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{path.as_posix()}"], cwd=root, capture_output=True
        )
        if tracked.returncode == 0:
            _git(root, "checkout", "HEAD", "--", str(path))
        else:
            _git(root, "rm", "--quiet", "--cached", "--ignore-unmatch", "--", str(path))
            (root / path).unlink(missing_ok=True)


def commit(root: Path, paths: set[Path], message: str) -> None:
    names = sorted(str(path) for path in paths)
    _git(root, "add", "--", *names)
    _git(root, "commit", "--quiet", "-m", message, "--", *names)


def tag(root: Path, name: str) -> None:
    _git(root, "tag", name)


def push(root: Path, tags: list[str]) -> None:
    _git(root, "push", "--quiet", "--atomic", "origin", default_branch(root), *tags)


def _git(root: Path, *args: str, hint: str = "", strip: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        suffix = f" ({hint})" if hint else ""
        raise ReleaseError(f"git {' '.join(args)} failed: {detail}{suffix}")
    return result.stdout.strip() if strip else result.stdout

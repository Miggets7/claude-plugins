"""Draft, translate, write and check the what's-new texts."""
import json
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from byrt_release.project import Project, ReleaseError
from byrt_release.versions import Version

Ask = Callable[[str, dict], dict]

SOURCE = Path("metadata/whats_new.txt")
ANDROID_LIMIT = 500
IOS_LIMIT = 4000
DRAFT_LIMIT = 450  # leaves room for translations, which tend to run longer than English

# Run from an empty directory with only project settings, so the caller's own hooks, plugins and
# instructions cannot reshape the text. No tools: the model only writes.
_CLAUDE = [
    "claude", "-p",
    "--setting-sources", "project",
    "--tools", "",
    "--disable-slash-commands",
    "--strict-mcp-config",
    "--no-session-persistence",
    "--output-format", "json",
]  # fmt: skip


def ask_claude(prompt: str, schema: dict) -> dict:
    with tempfile.TemporaryDirectory() as empty_dir:
        result = subprocess.run(
            [*_CLAUDE, "--json-schema", json.dumps(schema)],
            input=prompt,
            cwd=empty_dir,
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        raise ReleaseError(f"claude failed with exit code {result.returncode}: {result.stderr.strip()[-300:]}")
    try:
        reply = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ReleaseError("claude returned something that is not JSON") from None
    if reply.get("is_error") or not isinstance(reply.get("structured_output"), dict):
        raise ReleaseError(f"claude gave no usable answer: {str(reply.get('result'))[:300]}")
    return reply["structured_output"]


def tone_reference(root: Path) -> str:
    """Earlier what's-new texts, newest first: the last release, then the hand-written older files."""
    source = root / SOURCE
    legacy = sorted((root / "metadata").glob("release_notes_*.txt"), reverse=True)
    files = ([source] if source.is_file() else []) + legacy
    return "\n\n".join(f"--- {file.name} ---\n{file.read_text().strip()}" for file in files)


_STORE_NAMES = {"android": "Android", "ios": "iOS"}


def draft(commits: list[str], reference: str, platforms: list[str], ask: Ask) -> str:
    names = [_STORE_NAMES[platform] for platform in sorted(platforms)]
    released_on = " and ".join(names) if len(names) > 1 else f"{names[0]} only"
    prompt = f"""You write the "What's new" text that the App Store and Google Play show for a new \
version of a mobile app.

Write the text for this release from the commit messages below. This version is released on \
{released_on}.

Rules:
- Leave out changes that only affect a platform this version is not released on.
- Do not put a version number in the text, even if the earlier texts have one. The stores show it.
- Mention only changes a person using the app would notice. Leave out build tooling, CI, \
refactoring, tests, code review tooling, dependency updates and documentation.
- Match the tone, length and layout of the earlier texts.
- Plain text only. The stores show it as typed: no Markdown.
- At most {DRAFT_LIMIT} characters, line breaks included.
- If nothing in the commits is noticeable to a user, write one short line saying the release \
brings fixes and improvements, in the tone of the earlier texts.
- Write in English.

Earlier texts:
{reference or "(none)"}

Commit messages:
{chr(10).join(f"* {commit}" for commit in commits)}

Return the text in the "text" field."""
    schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }
    text = str(ask(prompt, schema).get("text", "")).strip()
    if not text:
        raise ReleaseError("the drafted what's-new text is empty")
    return text


def targets(project: Project, versions: dict[str, Version]) -> dict[Path, tuple[str, int]]:
    """Every store file this release writes, relative to the repo root, with its locale and limit."""
    result: dict[Path, tuple[str, int]] = {}
    for platform, version in sorted(versions.items()):
        base = Path("metadata") / platform
        folder = project.root / base
        locales = sorted(entry.name for entry in folder.iterdir() if entry.is_dir()) if folder.is_dir() else []
        if not locales:
            raise ReleaseError(f"{base} has no locale folders; run `release init` in this repo first")
        for locale in locales:
            if platform == "android":
                result[base / locale / "changelogs" / f"{version.build}.txt"] = (locale, ANDROID_LIMIT)
            else:
                result[base / locale / "release_notes.txt"] = (locale, IOS_LIMIT)
    return result


def translate(english: str, locales: set[str], ask: Ask) -> dict[str, str]:
    texts = {locale: english for locale in locales if locale.lower().startswith("en")}
    others = sorted(locales - texts.keys())
    if not others:
        return texts
    prompt = f"""Translate the app store "What's new" text below into each of these store locale \
codes: {", ".join(others)}.

Rules:
- Keep the meaning, the layout and the line breaks.
- Use the wording a native speaker expects in an app store. Do not translate product names.
- Each translation is at most {ANDROID_LIMIT} characters, line breaks included. Tighten the wording \
if needed; do not drop a point.
- Codes that name the same language (for example ja and ja-JP) get the identical text.
- Plain text only, no Markdown.

Text:
{english}

Return one property per locale code."""
    schema = {
        "type": "object",
        "properties": {locale: {"type": "string"} for locale in others},
        "required": others,
        "additionalProperties": False,
    }
    reply = ask(prompt, schema)
    for locale in others:
        if not str(reply.get(locale, "")).strip():
            raise ReleaseError(f"no translation came back for {locale}")
        texts[locale] = str(reply[locale]).strip()
    return texts


def read_source(root: Path) -> str:
    return (root / SOURCE).read_text().strip()


def write_all(
    root: Path, english: str, texts: dict[str, str], targets: dict[Path, tuple[str, int]]
) -> set[Path]:
    """Write the English source and every store file; returns the paths written, relative to root."""
    (root / SOURCE).parent.mkdir(parents=True, exist_ok=True)
    (root / SOURCE).write_text(english + "\n")
    for path, (locale, _) in targets.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(texts[locale])
    return {SOURCE, *targets}


def validate(root: Path, targets: dict[Path, tuple[str, int]]) -> None:
    problems = []
    for path, (_, limit) in sorted(targets.items()):
        file = root / path
        # Not stripped for the length: the store receives the file as it is, trailing newline included.
        text = file.read_text() if file.is_file() else ""
        if not text.strip():
            problems.append(f"{path} is missing or empty")
        elif len(text) > limit:
            problems.append(f"{path} has {len(text)} characters, the limit is {limit}")
    if problems:
        raise ReleaseError("what's-new texts need fixing: " + "; ".join(problems))

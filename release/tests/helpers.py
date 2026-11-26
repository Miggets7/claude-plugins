"""Shared test helpers."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="byrt-release-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def copy_fixture(self, name: str) -> Path:
        target = self.tmp / name
        shutil.copytree(FIXTURES / name, target)
        return target


def git(root: Path, *args: str) -> str:
    import subprocess

    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return result.stdout.strip()


class GitRepoTest(TempDirTest):
    """A clone on branch main with one pushed commit, and its bare remote."""

    def setUp(self):
        super().setUp()
        self.remote = self.tmp / "remote.git"
        git(self.tmp, "init", "--quiet", "--bare", "--initial-branch=main", str(self.remote))
        self.repo = self.tmp / "app"
        git(self.tmp, "clone", "--quiet", str(self.remote), str(self.repo))
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "commit.gpgsign", "false")
        git(self.repo, "checkout", "--quiet", "-b", "main")
        self.commit_file("README.md", "demo\n", "Initial commit")
        git(self.repo, "push", "--quiet", "-u", "origin", "main")
        git(self.repo, "remote", "set-head", "origin", "main")

    def remote_sha(self, ref: str) -> str:
        """The commit the bare remote has for a branch or tag. `--git-dir` keeps this working where
        git refuses to discover bare repositories (safe.bareRepository=explicit)."""
        return git(self.tmp, f"--git-dir={self.remote}", "rev-parse", ref)

    def commit_file(self, name: str, content: str, message: str) -> str:
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        git(self.repo, "add", name)
        git(self.repo, "commit", "--quiet", "-m", message)
        return git(self.repo, "rev-parse", "HEAD")


class FakeRunner:
    """Records calls; `on_call` lets a test play the part of the command."""

    def __init__(self, on_call=None, output: str = ""):
        self.calls: list[tuple[list[str], Path, dict[str, str]]] = []
        self.on_call = on_call
        self.output = output

    def __call__(self, argv, cwd, env):
        self.calls.append((list(argv), cwd, dict(env)))
        if self.on_call:
            result = self.on_call(argv)
            if result is not None:
                return result
        return self.output

    @property
    def argvs(self):
        return [argv for argv, _, _ in self.calls]


def option(argv: list[str], key: str) -> str:
    return next(arg.split(":", 1)[1] for arg in argv if arg.startswith(f"{key}:"))


class FakeAsk:
    def __init__(self, reply: dict | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.reply = reply

    def __call__(self, prompt: str, schema: dict) -> dict:
        self.calls.append((prompt, schema))
        if self.reply is not None:
            return self.reply
        return {code: f"[{code}] text" for code in schema["properties"]}


class ReleaseRepoTest(GitRepoTest):
    """A pushed Toolchain app repo with store locale folders, private state dir and fake commands."""

    STORE = {"android_code": 19, "ios_build": 14, "ios_live_name": "1.2.0"}

    def setUp(self):
        super().setUp()
        from unittest import mock

        from byrt_release import state
        from byrt_release.config import Config

        patcher = mock.patch.object(state, "CACHE_DIR", self.tmp / "cache")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.config = Config("KEYID12345", "issuer-id", self.tmp / "key.p8", self.tmp / "play.json")

        shutil.copytree(FIXTURES / "toolchain_plist", self.repo, dirs_exist_ok=True)
        for locale in ("en-US", "nl-NL"):
            self.write(f"metadata/ios/{locale}/release_notes.txt", "Old text.")
            self.write(f"metadata/android/{locale}/changelogs/19.txt", "Old text.")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "Add the app")
        git(self.repo, "push", "--quiet")
        self.runner = FakeRunner(on_call=self.play_command)
        self.ask = FakeAsk()
        self.store = dict(self.STORE)

    def write(self, name: str, content: str) -> None:
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def play_command(self, argv):
        """Stand in for the store and build commands the tool runs."""
        if argv[:2] == ["fastlane", "store_state"]:
            Path(option(argv, "out")).write_text(json.dumps(self.store))
        if argv[:2] == ["./kotlin", "package"]:
            aab = self.tmp / "app-release.aab"
            aab.write_text("aab")
            return f"Package created at: {aab}\n"
        return None

    def pushed_commit(self, name: str, message: str) -> str:
        sha = self.commit_file(name, "x\n", message)
        git(self.repo, "push", "--quiet")
        return sha

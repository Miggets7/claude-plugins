from byrt_release import cli, gitops, state
from byrt_release.project import ReleaseError

from tests.helpers import FakeRunner, ReleaseRepoTest, git


def step_of(argv: list[str]) -> str:
    """Name the ship step a recorded command belongs to."""
    if argv[:2] == ["./kotlin", "package"]:
        return "android_build"
    if argv[:2] == ["./kotlin", "publish"]:
        return "ios_publish"
    return argv[1]


class ShipTest(ReleaseRepoTest):
    def setUp(self):
        super().setUp()
        git(self.repo, "tag", "android-1.2.0-19")
        git(self.repo, "tag", "ios-1.2.0-14")
        self.pushed_commit("feature.txt", "Add Dutch translation")
        cli.prepare(self.repo, self.config, self.runner, self.ask, None, None, None, None)
        self.runner.calls.clear()

    def ship(self, runner=None, dry_run=False):
        cli.ship(self.repo, self.config, runner or self.runner, dry_run)

    def steps(self, runner=None):
        return [step_of(argv) for argv in (runner or self.runner).argvs]

    def failing_at(self, step: str) -> FakeRunner:
        def on_call(argv):
            if step_of(argv) == step:
                raise ReleaseError(f"{step} failed")
            return self.play_command(argv)

        return FakeRunner(on_call=on_call)

    def test_ship_runs_steps_in_order_then_commits_tags_pushes(self):
        self.ship()

        self.assertEqual(self.steps(), ["android_build", "ios_publish", "upload_android", "upload_ios_notes"])
        head = git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(
            git(self.repo, "log", "-1", "--format=%s"), "Release Android 1.2.1 (20) and iOS 1.2.1 (15)"
        )
        self.assertEqual(git(self.remote, "rev-parse", "main"), head)
        self.assertEqual(git(self.remote, "rev-parse", "android-1.2.1-20"), head)
        self.assertEqual(git(self.remote, "rev-parse", "ios-1.2.1-15"), head)
        self.assertEqual(gitops.changed_paths(self.repo), set())
        self.assertIsNone(state.load(self.repo))

    def test_release_commit_holds_versions_and_texts(self):
        self.ship()

        files = git(self.repo, "show", "--name-only", "--format=", "HEAD").splitlines()
        self.assertIn("androidApp/module.yaml", files)
        self.assertIn("iosApp/src/Info.plist", files)
        self.assertIn("metadata/whats_new.txt", files)
        self.assertIn("metadata/android/nl-NL/changelogs/20.txt", files)

    def test_ios_notes_name_the_new_version(self):
        self.ship()

        notes_call = next(argv for argv in self.runner.argvs if step_of(argv) == "upload_ios_notes")
        self.assertIn("app_version:1.2.1", notes_call)

    def test_android_only_release_skips_ios_steps_and_tags(self):
        cli.abort(self.repo)
        cli.prepare(self.repo, self.config, self.runner, self.ask, "android", None, None, None)
        self.runner.calls.clear()

        self.ship()

        self.assertEqual(self.steps(), ["android_build", "upload_android"])
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "Release Android 1.2.1 (20)")
        self.assertEqual(git(self.repo, "tag", "--list", "ios-1.2.1-*"), "")

    def test_ship_resumes_after_ios_failure(self):
        failing = self.failing_at("ios_publish")
        with self.assertRaisesRegex(ReleaseError, "ios_publish failed"):
            self.ship(failing)

        self.assertEqual(self.steps(failing), ["android_build", "ios_publish"])
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "Add Dutch translation")
        self.assertEqual(state.load(self.repo).done, ["android_build"])

        self.ship()

        self.assertEqual(self.steps(), ["android_build", "ios_publish", "upload_android", "upload_ios_notes"])
        self.assertIsNone(state.load(self.repo))

    def test_resume_does_not_repeat_finished_uploads(self):
        failing = self.failing_at("upload_ios_notes")
        with self.assertRaises(ReleaseError):
            self.ship(failing)

        self.ship()

        self.assertEqual(self.steps(), ["upload_ios_notes"])
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "Release Android 1.2.1 (20) and iOS 1.2.1 (15)")

    def test_ship_resumes_at_push(self):
        git(self.repo, "remote", "set-url", "--push", "origin", str(self.tmp / "missing.git"))
        with self.assertRaisesRegex(ReleaseError, "push"):
            self.ship()
        self.assertEqual(state.load(self.repo).done[-2:], ["commit", "tag"])
        git(self.repo, "remote", "set-url", "--push", "origin", str(self.remote))
        self.runner.calls.clear()

        self.ship()

        self.assertEqual(self.runner.calls, [])
        head = git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(git(self.remote, "rev-parse", "main"), head)
        self.assertEqual(git(self.remote, "rev-parse", "android-1.2.1-20"), head)
        self.assertEqual(git(self.repo, "rev-list", "--count", "origin/main"), "4")
        self.assertEqual(len(git(self.repo, "tag", "--list", "android-1.2.1-*").splitlines()), 1)

    def test_ship_refuses_when_head_moved(self):
        git(self.repo, "stash", "--quiet", "--include-untracked")
        self.commit_file("other.txt", "x\n", "Unrelated commit")
        git(self.repo, "stash", "pop", "--quiet")

        with self.assertRaisesRegex(ReleaseError, "release prepare"):
            self.ship()
        self.assertEqual(self.runner.calls, [])

    def test_ship_refuses_unrelated_change(self):
        self.write("stray.txt", "x")

        with self.assertRaisesRegex(ReleaseError, "stray.txt"):
            self.ship()
        self.assertEqual(self.runner.calls, [])

    def test_ship_refuses_when_a_version_file_lost_its_bump(self):
        git(self.repo, "checkout", "HEAD", "--", "androidApp/module.yaml")

        with self.assertRaisesRegex(ReleaseError, r"Android.*1\.2\.0 \(19\).*1\.2\.1 \(20\)"):
            self.ship()
        self.assertEqual(self.runner.calls, [])

    def test_ship_refuses_stale_translations(self):
        self.write("metadata/whats_new.txt", "Edited after translating.\n")

        with self.assertRaisesRegex(ReleaseError, "release translate"):
            self.ship()
        self.assertEqual(self.runner.calls, [])

    def test_ship_refuses_text_over_the_limit(self):
        self.write("metadata/android/nl-NL/changelogs/20.txt", "x" * 501)

        with self.assertRaisesRegex(ReleaseError, "501"):
            self.ship()
        self.assertEqual(self.runner.calls, [])

    def test_ship_without_prepare_is_an_error(self):
        cli.abort(self.repo)

        with self.assertRaisesRegex(ReleaseError, "release prepare"):
            self.ship()

    def test_dry_run_calls_nothing(self):
        head = git(self.repo, "rev-parse", "HEAD")
        before = state.load(self.repo)

        self.ship(dry_run=True)

        self.assertEqual(self.runner.calls, [])
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), head)
        self.assertEqual(state.load(self.repo), before)
        self.assertEqual(git(self.repo, "tag", "--list", "android-1.2.1-*"), "")

from pathlib import Path

from byrt_release import cli, gitops, state
from byrt_release.project import ReleaseError, detect
from byrt_release.versions import Version, read_android, read_ios

from tests.helpers import FIXTURES, FakeAsk, ReleaseRepoTest, git


class PrepareTest(ReleaseRepoTest):
    def setUp(self):
        super().setUp()
        git(self.repo, "tag", "android-1.2.0-19")
        git(self.repo, "tag", "ios-1.2.0-14")
        self.pushed_commit("feature.txt", "Add Dutch translation")

    def prepare(self, **options):
        defaults = {"only": None, "android_version": None, "ios_version": None, "since": None}
        cli.prepare(self.repo, self.config, self.runner, self.ask, **{**defaults, **options})

    def test_prepare_bumps_both_and_writes_notes(self):
        head = git(self.repo, "rev-parse", "HEAD")

        self.prepare()

        project = detect(self.repo)
        self.assertEqual(read_android(project.android), Version("1.2.1", 20))
        self.assertEqual(read_ios(project.ios), Version("1.2.1", 15))
        self.assertEqual((self.repo / "metadata/whats_new.txt").read_text(), "[text] text\n")
        self.assertEqual((self.repo / "metadata/android/nl-NL/changelogs/20.txt").read_text(), "[nl-NL] text")
        self.assertEqual((self.repo / "metadata/ios/en-US/release_notes.txt").read_text(), "[text] text")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), head)
        saved = state.load(self.repo)
        self.assertEqual(saved.head, head)
        self.assertEqual(saved.platforms, {"android": Version("1.2.1", 20), "ios": Version("1.2.1", 15)})
        self.assertEqual({Path(path) for path in saved.touched}, gitops.changed_paths(self.repo))
        self.assertEqual(saved.done, [])

    def test_draft_gets_the_commits_since_the_tags(self):
        self.prepare()

        draft_prompt = self.ask.calls[0][0]
        self.assertIn("Add Dutch translation", draft_prompt)
        self.assertNotIn("Add the app", draft_prompt)

    def test_draft_gets_the_previous_text_as_reference(self):
        self.write("metadata/whats_new.txt", "Earlier release text.\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "Add earlier text")
        git(self.repo, "push", "--quiet")

        self.prepare()

        self.assertIn("Earlier release text.", self.ask.calls[0][0])

    def test_prepare_only_android_leaves_ios_untouched(self):
        self.prepare(only="android")

        project = detect(self.repo)
        self.assertEqual(read_android(project.android), Version("1.2.1", 20))
        self.assertEqual(read_ios(project.ios), Version("1.2.0", 1))
        self.assertEqual(list(state.load(self.repo).platforms), ["android"])
        self.assertFalse(any("ios" in str(path) for path in gitops.changed_paths(self.repo)))

    def test_only_a_platform_the_repo_lacks_is_an_error(self):
        with self.assertRaisesRegex(ReleaseError, "no ios app"):
            cli.platforms_to_release(detect(FIXTURES / "gradle"), "ios")

    def test_repo_with_one_platform_releases_that_platform(self):
        self.assertEqual(cli.platforms_to_release(detect(FIXTURES / "gradle"), None), ["android"])

    def test_version_overrides_are_used(self):
        self.prepare(android_version="2.0", ios_version="3.0")

        self.assertEqual(
            state.load(self.repo).platforms, {"android": Version("2.0", 20), "ios": Version("3.0", 15)}
        )

    def test_prepare_without_tag_needs_since(self):
        git(self.repo, "tag", "-d", "ios-1.2.0-14")

        with self.assertRaisesRegex(ReleaseError, "--since"):
            self.prepare()
        self.assertEqual(gitops.changed_paths(self.repo), set())

    def test_since_stands_in_for_a_missing_tag(self):
        git(self.repo, "tag", "-d", "ios-1.2.0-14")
        git(self.repo, "tag", "-d", "android-1.2.0-19")

        self.prepare(since="HEAD~1")

        self.assertIn("Add Dutch translation", self.ask.calls[0][0])

    def test_prepare_stops_when_no_commits(self):
        git(self.repo, "tag", "-f", "android-1.2.0-19")
        git(self.repo, "tag", "-f", "ios-1.2.0-14")

        with self.assertRaisesRegex(ReleaseError, "nothing to release"):
            self.prepare()
        self.assertEqual(gitops.changed_paths(self.repo), set())
        self.assertIsNone(state.load(self.repo))
        self.assertEqual(self.runner.calls, [])

    def test_prepare_failure_restores_files(self):
        def failing_ask(prompt, schema):
            raise ReleaseError("claude failed")

        with self.assertRaisesRegex(ReleaseError, "claude failed"):
            cli.prepare(self.repo, self.config, self.runner, failing_ask, None, None, None, None)

        self.assertEqual(gitops.changed_paths(self.repo), set())
        self.assertIsNone(state.load(self.repo))

    def test_prepare_refuses_dirty_tree(self):
        self.write("stray.txt", "x")

        with self.assertRaisesRegex(ReleaseError, "stray.txt"):
            self.prepare()

    def test_prepare_twice_is_refused(self):
        self.prepare()

        with self.assertRaisesRegex(ReleaseError, "already prepared"):
            self.prepare()

    def test_too_long_translation_is_named_and_the_work_is_kept(self):
        long_ask = FakeAsk()
        long_ask.reply = None
        original = long_ask.__call__

        def ask(prompt, schema):
            reply = original(prompt, schema)
            if "nl-NL" in reply:
                reply["nl-NL"] = "x" * 501
            return reply

        with self.assertRaisesRegex(ReleaseError, r"metadata/android/nl-NL/changelogs/20\.txt.*501"):
            cli.prepare(self.repo, self.config, self.runner, ask, None, None, None, None)

        self.assertIsNotNone(state.load(self.repo))
        self.assertTrue((self.repo / "metadata/whats_new.txt").is_file())


class TranslateAndAbortTest(ReleaseRepoTest):
    def setUp(self):
        super().setUp()
        git(self.repo, "tag", "android-1.2.0-19")
        git(self.repo, "tag", "ios-1.2.0-14")
        self.pushed_commit("feature.txt", "Add Dutch translation")
        cli.prepare(self.repo, self.config, self.runner, self.ask, None, None, None, None)

    def test_translate_rewrites_locale_files_from_the_edited_source(self):
        before = state.load(self.repo)
        self.write("metadata/whats_new.txt", "Edited by hand.\n")

        cli.translate(self.repo, FakeAsk(reply={"nl-NL": "Met de hand bewerkt."}))

        self.assertEqual((self.repo / "metadata/ios/en-US/release_notes.txt").read_text(), "Edited by hand.")
        self.assertEqual(
            (self.repo / "metadata/android/nl-NL/changelogs/20.txt").read_text(), "Met de hand bewerkt."
        )
        after = state.load(self.repo)
        self.assertNotEqual(after.english_sha256, before.english_sha256)
        self.assertEqual(after.touched, before.touched)

    def test_translate_without_a_prepared_release_is_an_error(self):
        state.clear(self.repo)

        with self.assertRaisesRegex(ReleaseError, "release prepare"):
            cli.translate(self.repo, self.ask)

    def test_translate_after_a_store_got_the_texts_is_refused(self):
        for sent in ("android_upload", "ios_notes"):
            saved = state.load(self.repo)
            saved.done = ["android_build", "ios_publish", sent]
            state.save(self.repo, saved)

            with self.assertRaisesRegex(ReleaseError, "release ship"):
                cli.translate(self.repo, self.ask)

    def test_translate_after_the_testflight_upload_is_allowed(self):
        saved = state.load(self.repo)
        saved.done = ["android_build", "ios_publish"]
        state.save(self.repo, saved)
        self.write("metadata/whats_new.txt", "Edited by hand.\n")

        cli.translate(self.repo, FakeAsk(reply={"nl-NL": "Met de hand bewerkt."}))

        self.assertEqual(state.load(self.repo).done, ["android_build", "ios_publish"])

    def test_abort_restores_tree_and_clears_state(self):
        cli.abort(self.repo)

        self.assertEqual(gitops.changed_paths(self.repo), set())
        self.assertIsNone(state.load(self.repo))
        self.assertEqual(read_android(detect(self.repo).android), Version("1.2.0", 19))

    def test_abort_keeps_a_hand_edit_in_a_version_file(self):
        module = self.repo / "androidApp/module.yaml"
        module.write_text(module.read_text() + "    minSdk: 26\n")

        cli.abort(self.repo)

        self.assertIn("minSdk: 26", module.read_text())
        self.assertEqual(read_android(detect(self.repo).android), Version("1.2.0", 19))
        self.assertEqual(gitops.changed_paths(self.repo), {Path("androidApp/module.yaml")})

    def test_prepare_records_the_versions_it_replaced(self):
        self.assertEqual(
            state.load(self.repo).previous, {"android": Version("1.2.0", 19), "ios": Version("1.2.0", 1)}
        )

    def test_abort_after_the_release_commit_is_refused(self):
        saved = state.load(self.repo)
        saved.done = ["android_build", "ios_publish", "android_upload", "ios_notes", "commit"]
        state.save(self.repo, saved)

        with self.assertRaisesRegex(ReleaseError, "release ship"):
            cli.abort(self.repo)


class MainTest(ReleaseRepoTest):
    def test_release_error_becomes_exit_code_one_with_a_message(self):
        import contextlib
        import io

        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = cli.main(["abort"], root=self.repo)

        self.assertEqual(code, 1)
        self.assertIn("release:", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())

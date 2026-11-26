from pathlib import Path

from byrt_release import cli

from tests.helpers import FakeRunner, ReleaseRepoTest, git, option


class InitTest(ReleaseRepoTest):
    def setUp(self):
        super().setUp()
        git(self.repo, "rm", "--quiet", "-r", "metadata")
        git(self.repo, "commit", "--quiet", "-m", "Start without metadata")

    def listing(self, ios: dict[str, str], android: dict[str, str]) -> FakeRunner:
        def fetch(argv):
            for locale, text in ios.items():
                folder = Path(option(argv, "ios_dir")) / locale
                folder.mkdir(parents=True)
                (folder / "release_notes.txt").write_text(text)
            for locale, text in android.items():
                folder = Path(option(argv, "android_dir")) / locale / "changelogs"
                folder.mkdir(parents=True)
                (folder / "19.txt").write_text(text)

        return FakeRunner(on_call=fetch)

    def test_init_fetches_the_listing_and_creates_the_english_source(self):
        runner = self.listing({"nl-NL": "Nu sneller.", "en-US": "Now faster."}, {"en-US": "Now faster on Android."})

        cli.init(self.repo, self.config, runner)

        self.assertEqual(runner.argvs[0][:2], ["fastlane", "fetch_listing"])
        self.assertEqual((self.repo / "metadata/whats_new.txt").read_text(), "Now faster.\n")

    def test_init_takes_english_from_android_when_ios_has_none(self):
        runner = self.listing({"nl-NL": "Nu sneller."}, {"en-GB": "Now faster on Android."})

        cli.init(self.repo, self.config, runner)

        self.assertEqual((self.repo / "metadata/whats_new.txt").read_text(), "Now faster on Android.\n")

    def test_init_never_overwrites_an_existing_source(self):
        self.write("metadata/whats_new.txt", "Kept.\n")

        cli.init(self.repo, self.config, self.listing({"en-US": "Now faster."}, {}))

        self.assertEqual((self.repo / "metadata/whats_new.txt").read_text(), "Kept.\n")

    def test_init_without_english_text_creates_no_source(self):
        cli.init(self.repo, self.config, self.listing({"nl-NL": "Nu sneller."}, {}))

        self.assertFalse((self.repo / "metadata/whats_new.txt").exists())

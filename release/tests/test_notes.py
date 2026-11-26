from pathlib import Path

from byrt_release import notes
from byrt_release.project import ReleaseError, detect
from byrt_release.versions import Version

from tests.helpers import FakeAsk, TempDirTest


class NotesTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.root = self.copy_fixture("toolchain_plist")
        self.project = detect(self.root)
        self.versions = {"android": Version("1.2.1", 20), "ios": Version("1.2.1", 15)}

    def locales(self, platform: str, *codes: str) -> None:
        for code in codes:
            folder = self.root / "metadata" / platform / code
            (folder / "changelogs" if platform == "android" else folder).mkdir(parents=True)


class TargetsTest(NotesTest):
    def test_targets_follow_locale_folders(self):
        self.locales("ios", "en-US", "nl-NL")
        self.locales("android", "en-US", "nl-NL")

        self.assertEqual(
            notes.targets(self.project, self.versions),
            {
                Path("metadata/android/en-US/changelogs/20.txt"): ("en-US", 500),
                Path("metadata/android/nl-NL/changelogs/20.txt"): ("nl-NL", 500),
                Path("metadata/ios/en-US/release_notes.txt"): ("en-US", 4000),
                Path("metadata/ios/nl-NL/release_notes.txt"): ("nl-NL", 4000),
            },
        )

    def test_platform_that_is_not_released_contributes_no_files(self):
        self.locales("ios", "en-US")
        self.locales("android", "en-US")

        result = notes.targets(self.project, {"android": Version("1.2.1", 20)})

        self.assertEqual(list(result), [Path("metadata/android/en-US/changelogs/20.txt")])

    def test_released_platform_without_locale_folders_is_an_error(self):
        self.locales("ios", "en-US")

        with self.assertRaisesRegex(ReleaseError, "release init"):
            notes.targets(self.project, self.versions)


class TranslateTest(NotesTest):
    def test_english_locales_skip_translation(self):
        ask = FakeAsk()

        texts = notes.translate("Hello", {"en-US", "en-GB", "nl-NL"}, ask)

        self.assertEqual(texts, {"en-US": "Hello", "en-GB": "Hello", "nl-NL": "[nl-NL] text"})
        self.assertEqual(len(ask.calls), 1)
        self.assertEqual(set(ask.calls[0][1]["properties"]), {"nl-NL"})
        self.assertEqual(ask.calls[0][1]["required"], ["nl-NL"])

    def test_only_english_locales_need_no_model_call(self):
        ask = FakeAsk()

        self.assertEqual(notes.translate("Hello", {"en-US"}, ask), {"en-US": "Hello"})
        self.assertEqual(ask.calls, [])

    def test_translation_prompt_holds_the_english_text(self):
        ask = FakeAsk()

        notes.translate("Fixed the crash on start.", {"de-DE"}, ask)

        self.assertIn("Fixed the crash on start.", ask.calls[0][0])

    def test_missing_translation_is_an_error(self):
        with self.assertRaisesRegex(ReleaseError, "de-DE"):
            notes.translate("Hello", {"de-DE", "nl-NL"}, FakeAsk(reply={"nl-NL": "Hallo"}))


class DraftTest(NotesTest):
    def test_draft_prompt_contains_commits_and_reference(self):
        ask = FakeAsk(reply={"text": "  Now in Dutch.\n"})

        text = notes.draft(
            ["Add Dutch translation", "Fix crash on start"], "v1.1 - Now in 9 languages", ["android", "ios"], ask
        )

        self.assertEqual(text, "Now in Dutch.")
        prompt = ask.calls[0][0]
        self.assertIn("Add Dutch translation", prompt)
        self.assertIn("Fix crash on start", prompt)
        self.assertIn("v1.1 - Now in 9 languages", prompt)

    def test_draft_prompt_names_only_the_released_platform(self):
        ask = FakeAsk(reply={"text": "Fixes."})

        notes.draft(["Fix crash on start"], "", ["android"], ask)

        self.assertIn("released on Android only", ask.calls[0][0])

    def test_draft_prompt_for_both_platforms_says_so(self):
        ask = FakeAsk(reply={"text": "Fixes."})

        notes.draft(["Fix crash on start"], "", ["android", "ios"], ask)

        self.assertIn("released on Android and iOS", ask.calls[0][0])

    def test_empty_draft_is_an_error(self):
        with self.assertRaisesRegex(ReleaseError, "empty"):
            notes.draft(["Fix"], "", ["android"], FakeAsk(reply={"text": "  "}))

    def test_tone_reference_includes_legacy_notes(self):
        metadata = self.root / "metadata"
        metadata.mkdir()
        (metadata / "release_notes_v1.0.txt").write_text("First release.")
        (metadata / "release_notes_v1.1.txt").write_text("Now in 9 languages.")
        (metadata / "whats_new.txt").write_text("Faster start.\n")

        reference = notes.tone_reference(self.root)

        self.assertLess(reference.index("Faster start."), reference.index("Now in 9 languages."))
        self.assertLess(reference.index("Now in 9 languages."), reference.index("First release."))

    def test_tone_reference_without_any_earlier_text_is_empty(self):
        self.assertEqual(notes.tone_reference(self.root), "")


class WriteAndValidateTest(NotesTest):
    def setUp(self):
        super().setUp()
        self.locales("ios", "en-US", "nl-NL")
        self.locales("android", "en-US", "nl-NL")
        self.targets = notes.targets(self.project, self.versions)

    def test_write_all_writes_source_and_every_target(self):
        written = notes.write_all(self.root, "Hello", {"en-US": "Hello", "nl-NL": "Hallo"}, self.targets)

        self.assertEqual(written, {notes.SOURCE, *self.targets})
        self.assertEqual((self.root / "metadata/whats_new.txt").read_text(), "Hello\n")
        self.assertEqual((self.root / "metadata/android/nl-NL/changelogs/20.txt").read_text(), "Hallo")
        self.assertEqual((self.root / "metadata/ios/nl-NL/release_notes.txt").read_text(), "Hallo")

    def test_read_source_strips_the_trailing_newline(self):
        notes.write_all(self.root, "Hello", {"en-US": "Hello", "nl-NL": "Hallo"}, self.targets)

        self.assertEqual(notes.read_source(self.root), "Hello")

    def test_validate_accepts_text_at_the_limit(self):
        notes.write_all(self.root, "x", {"en-US": "x" * 500, "nl-NL": "y" * 500}, self.targets)

        notes.validate(self.root, self.targets)

    def test_validate_names_file_over_limit(self):
        notes.write_all(self.root, "x", {"en-US": "x" * 500, "nl-NL": "y" * 501}, self.targets)

        with self.assertRaisesRegex(ReleaseError, r"metadata/android/nl-NL/changelogs/20\.txt.*501") as raised:
            notes.validate(self.root, self.targets)
        self.assertNotIn("metadata/ios/nl-NL", str(raised.exception))

    def test_validate_counts_a_trailing_newline_because_the_store_receives_it(self):
        notes.write_all(self.root, "x", {"en-US": "x", "nl-NL": "y"}, self.targets)
        (self.root / "metadata/android/nl-NL/changelogs/20.txt").write_text("y" * 500 + "\n")

        with self.assertRaisesRegex(ReleaseError, r"nl-NL/changelogs/20\.txt.*501"):
            notes.validate(self.root, self.targets)

    def test_validate_names_missing_or_empty_file(self):
        notes.write_all(self.root, "x", {"en-US": "x", "nl-NL": ""}, self.targets)

        with self.assertRaisesRegex(ReleaseError, "nl-NL.*empty"):
            notes.validate(self.root, self.targets)

import difflib

from byrt_release.project import ReleaseError, detect
from byrt_release.versions import (
    Version,
    bump_name,
    next_version,
    read_android,
    read_ios,
    write_android,
    write_ios,
)

from tests.helpers import FIXTURES, TempDirTest


def changed_lines(before: str, after: str) -> list[str]:
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
    return [line[1:].strip() for line in diff if line.startswith("+") and not line.startswith("+++")]


class ReadTest(TempDirTest):
    def test_reads_toolchain_android(self):
        self.assertEqual(read_android(detect(FIXTURES / "toolchain_plist").android), Version("1.2.0", 19))

    def test_reads_gradle_android(self):
        self.assertEqual(read_android(detect(FIXTURES / "gradle").android), Version("1.9.0", 26))

    def test_reads_ios_from_plist(self):
        self.assertEqual(read_ios(detect(FIXTURES / "toolchain_plist").ios), Version("1.2.0", 1))

    def test_reads_ios_from_pbxproj(self):
        self.assertEqual(read_ios(detect(FIXTURES / "toolchain_pbx").ios), Version("1.1", 2))

    def test_reads_ios_name_from_pbxproj_and_build_from_plist(self):
        self.assertEqual(read_ios(detect(FIXTURES / "xcode").ios), Version("1.72", 410))


class WriteTest(TempDirTest):
    def test_toolchain_android_write_changes_only_the_two_values(self):
        target = detect(self.copy_fixture("toolchain_plist")).android
        before = target.version_file.read_text()

        write_android(target, Version("1.2.1", 20))

        self.assertEqual(read_android(target), Version("1.2.1", 20))
        self.assertEqual(
            changed_lines(before, target.version_file.read_text()),
            ["versionCode: 20", 'versionName: "1.2.1"'],
        )

    def test_gradle_write_changes_only_the_two_values(self):
        target = detect(self.copy_fixture("gradle")).android
        before = target.version_file.read_text()

        write_android(target, Version("1.9.1", 27))

        self.assertEqual(
            changed_lines(before, target.version_file.read_text()),
            ["versionCode = 27", 'versionName = "1.9.1"'],
        )

    def test_plist_write_changes_only_the_two_values(self):
        target = detect(self.copy_fixture("toolchain_plist")).ios
        before = target.name_file.read_text()

        write_ios(target, Version("1.2.1", 15))

        self.assertEqual(read_ios(target), Version("1.2.1", 15))
        self.assertEqual(
            changed_lines(before, target.name_file.read_text()),
            ["<string>1.2.1</string>", "<string>15</string>"],
        )

    def test_pbxproj_write_updates_every_build_configuration(self):
        target = detect(self.copy_fixture("toolchain_pbx")).ios
        before = target.name_file.read_text()

        write_ios(target, Version("1.2", 3))

        self.assertEqual(
            changed_lines(before, target.name_file.read_text()),
            ["CURRENT_PROJECT_VERSION = 3;", "MARKETING_VERSION = 1.2;"] * 2,
        )

    def test_split_ios_write_touches_both_files(self):
        target = detect(self.copy_fixture("xcode")).ios

        write_ios(target, Version("1.73", 411))

        self.assertEqual(read_ios(target), Version("1.73", 411))
        self.assertIn("$(MARKETING_VERSION)", target.build_file.read_text())


class BumpNameTest(TempDirTest):
    def test_raises_the_last_number(self):
        self.assertEqual(bump_name("1.26"), "1.27")
        self.assertEqual(bump_name("1.2.0"), "1.2.1")
        self.assertEqual(bump_name("1.9"), "1.10")

    def test_name_that_is_not_dotted_numbers_is_an_error(self):
        with self.assertRaisesRegex(ReleaseError, "1.2.0-beta"):
            bump_name("1.2.0-beta")


class NextVersionTest(TempDirTest):
    def test_build_follows_the_store_when_the_repo_lags(self):
        self.assertEqual(next_version(Version("1.2.0", 1), 14, None, None), Version("1.2.1", 15))

    def test_build_follows_the_repo_when_it_is_ahead(self):
        self.assertEqual(next_version(Version("1.2.0", 19), 18, None, None).build, 20)

    def test_build_without_store_data_is_repo_plus_one(self):
        self.assertEqual(next_version(Version("1.2.0", 19), None, None, None).build, 20)

    def test_name_override_is_used_as_given(self):
        self.assertEqual(next_version(Version("1.2.0", 19), None, None, "2.0").name, "2.0")

    def test_name_must_be_above_the_live_store_version(self):
        with self.assertRaisesRegex(ReleaseError, "1.10"):
            next_version(Version("1.8", 5), 5, "1.10", None)

    def test_name_is_compared_as_numbers(self):
        self.assertEqual(next_version(Version("1.9", 5), 5, "1.9", None).name, "1.10")

    def test_override_that_is_not_dotted_numbers_is_an_error(self):
        with self.assertRaises(ReleaseError):
            next_version(Version("1.9", 5), 5, "1.9", "next")

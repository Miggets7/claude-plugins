from byrt_release.project import Kind, ReleaseError, detect

from tests.helpers import FIXTURES, TempDirTest


class DetectTest(TempDirTest):
    def test_detects_toolchain_repo_with_both_targets(self):
        project = detect(FIXTURES / "toolchain_plist")

        self.assertEqual(project.kind, Kind.TOOLCHAIN)
        self.assertEqual(project.android.application_id, "com.example.plistapp")
        self.assertEqual(project.android.version_file, FIXTURES / "toolchain_plist/androidApp/module.yaml")
        self.assertEqual(project.ios.bundle_id, "com.example.plistapp")
        self.assertEqual(project.ios.team_id, "ABCDE12345")
        self.assertEqual(project.ios.xcodeproj, FIXTURES / "toolchain_plist/iosApp/module.xcodeproj")

    def test_ios_values_in_plist_are_read_from_plist(self):
        ios = detect(FIXTURES / "toolchain_plist").ios

        self.assertEqual(ios.name_file, FIXTURES / "toolchain_plist/iosApp/src/Info.plist")
        self.assertEqual(ios.build_file, FIXTURES / "toolchain_plist/iosApp/src/Info.plist")

    def test_ios_values_missing_from_plist_come_from_pbxproj(self):
        ios = detect(FIXTURES / "toolchain_pbx").ios

        pbxproj = FIXTURES / "toolchain_pbx/iosApp/module.xcodeproj/project.pbxproj"
        self.assertEqual(ios.name_file, pbxproj)
        self.assertEqual(ios.build_file, pbxproj)

    def test_plist_value_that_is_a_build_setting_reference_comes_from_pbxproj(self):
        ios = detect(FIXTURES / "xcode").ios

        self.assertEqual(ios.name_file, FIXTURES / "xcode/Demo.xcodeproj/project.pbxproj")
        self.assertEqual(ios.build_file, FIXTURES / "xcode/Demo/Info.plist")

    def test_detects_gradle_repo_without_ios(self):
        project = detect(FIXTURES / "gradle")

        self.assertEqual(project.kind, Kind.GRADLE)
        self.assertEqual(project.android.application_id, "com.example.gradleapp")
        self.assertIsNone(project.ios)

    def test_detects_xcode_repo_without_android(self):
        project = detect(FIXTURES / "xcode")

        self.assertEqual(project.kind, Kind.XCODE)
        self.assertEqual(project.ios.bundle_id, "com.example.xcodeapp")
        self.assertIsNone(project.android)

    def test_unknown_directory_is_an_error(self):
        with self.assertRaisesRegex(ReleaseError, "not an app repo"):
            detect(self.tmp)

    def test_two_different_bundle_ids_are_an_error(self):
        root = self.copy_fixture("xcode")
        pbxproj = root / "Demo.xcodeproj/project.pbxproj"
        pbxproj.write_text(pbxproj.read_text().replace("com.example.xcodeapp", "com.example.other", 1))

        with self.assertRaisesRegex(ReleaseError, "PRODUCT_BUNDLE_IDENTIFIER"):
            detect(root)

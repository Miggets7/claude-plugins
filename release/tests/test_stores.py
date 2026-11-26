import contextlib
import io
import json
import os
import plistlib
import time
from pathlib import Path

from byrt_release import stores
from byrt_release.config import Config
from byrt_release.project import ReleaseError, detect
from byrt_release.stores import StoreState

from tests.helpers import FIXTURES, FakeRunner, TempDirTest, option

KEY_ID = "KEYID12345"
ISSUER_ID = "11111111-2222-3333-4444-555555555555"


class StoresTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.p8 = self.tmp / "AuthKey.p8"
        self.p8.write_text("p8-secret-content")
        self.play = self.tmp / "play.json"
        self.play.write_text('{"private_key": "play-secret-content"}')
        self.config = Config(KEY_ID, ISSUER_ID, self.p8, self.play)


class RunTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def script(self, body: str) -> list[str]:
        path = self.tmp / "script.sh"
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
        return [str(path)]

    def test_returns_the_output(self):
        self.assertIn("hello", stores.run(self.script("echo hello\n"), self.tmp, {}))

    def test_passes_extra_environment(self):
        self.assertIn("value-1", stores.run(self.script('echo "$EXTRA"\n'), self.tmp, {"EXTRA": "value-1"}))

    def test_fails_on_nonzero_exit(self):
        with self.assertRaisesRegex(ReleaseError, "exit code 3"):
            stores.run(self.script("exit 3\n"), self.tmp, {})

    def kotlin(self, body: str) -> list[str]:
        path = self.tmp / "kotlin"
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
        return ["./kotlin"]

    def test_kotlin_error_line_with_exit_zero_is_a_failure(self):
        with self.assertRaisesRegex(ReleaseError, "ERROR: Task failed"):
            stores.run(self.kotlin("echo 'ERROR: Task failed'\nexit 0\n"), self.tmp, {})

    def test_kotlin_error_line_inside_a_diagnostic_box_is_a_failure(self):
        with self.assertRaisesRegex(ReleaseError, "ERROR: Unresolved reference"):
            stores.run(self.kotlin("echo '    ╭─ ERROR: Unresolved reference'\n"), self.tmp, {})

    def test_kotlin_line_with_the_word_error_inside_is_not_a_failure(self):
        stores.run(self.kotlin("echo 'Compiled with 0 ERROR: none'\n"), self.tmp, {})

    def test_error_line_from_another_command_is_not_a_failure(self):
        stores.run(self.script("echo 'ERROR: printed by a store tool that exited 0'\n"), self.tmp, {})

    def test_failure_message_does_not_show_the_environment(self):
        with self.assertRaises(ReleaseError) as raised:
            stores.run(self.script("exit 1\n"), self.tmp, {"EXTRA": "value-1"})

        self.assertNotIn("value-1", str(raised.exception))


class SecretsTest(StoresTest):
    def test_no_secret_in_argv(self):
        def play_command(argv):
            if any(arg.startswith("out:") for arg in argv):
                Path(option(argv, "out")).write_text("{}")
            if argv[:2] == ["./kotlin", "package"]:
                aab = self.tmp / "fresh.aab"
                aab.write_text("aab")
                return f"Package created at: {aab}\n"

        for fixture in ("toolchain_plist", "xcode"):
            project = detect(FIXTURES / fixture)
            runner = FakeRunner(on_call=play_command)
            stores.store_state(project, self.config, runner)
            stores.fetch_listing(project, self.config, runner)
            stores.publish_ios(project, self.config, runner)
            stores.upload_ios_notes(project, "1.2.1", self.config, runner)
            if project.android:
                aab = stores.build_android(project, runner)
                stores.upload_android(project, aab, self.config, runner)

            for argv, _, _ in runner.calls:
                joined = " ".join(argv)
                for key_content in ("p8-secret-content", "play-secret-content"):
                    self.assertNotIn(key_content, joined)
                if argv[0] != "xcodebuild":  # xcodebuild takes the key id and issuer id only as flags
                    self.assertNotIn(KEY_ID, joined)
                    self.assertNotIn(ISSUER_ID, joined)

    def test_keys_travel_as_paths_and_ids_in_the_environment(self):
        runner = FakeRunner()

        stores.publish_ios(detect(FIXTURES / "toolchain_plist"), self.config, runner)

        env = runner.calls[0][2]
        self.assertEqual(env["KOTLIN_TOOLCHAIN_ASC_KEY_PATH"], str(self.p8))
        self.assertEqual(env["KOTLIN_TOOLCHAIN_ASC_KEY_ID"], KEY_ID)
        self.assertEqual(env["KOTLIN_TOOLCHAIN_ASC_KEY_ISSUER_ID"], ISSUER_ID)
        self.assertNotIn("p8-secret-content", " ".join(env.values()))


class StoreStateTest(StoresTest):
    def test_reads_numbers_the_lane_wrote(self):
        def lane(argv):
            Path(option(argv, "out")).write_text(
                json.dumps({"android_code": 19, "ios_build": 14, "ios_live_name": "1.2.0"})
            )

        runner = FakeRunner(on_call=lane)

        state = stores.store_state(detect(FIXTURES / "toolchain_plist"), self.config, runner)

        self.assertEqual(state, StoreState(android_code=19, ios_build=14, ios_live_name="1.2.0"))
        argv, cwd, env = runner.calls[0]
        self.assertEqual(argv[:2], ["fastlane", "store_state"])
        self.assertIn("bundle_id:com.example.plistapp", argv)
        self.assertIn("package_name:com.example.plistapp", argv)
        self.assertTrue((cwd / "fastlane" / "Fastfile").is_file())
        self.assertEqual(env["SUPPLY_JSON_KEY"], str(self.play))

    def test_android_only_repo_asks_only_for_play(self):
        runner = FakeRunner(on_call=lambda argv: Path(option(argv, "out")).write_text('{"android_code": 26}'))

        state = stores.store_state(detect(FIXTURES / "gradle"), self.config, runner)

        self.assertEqual(state, StoreState(android_code=26, ios_build=None, ios_live_name=None))
        self.assertFalse(any(arg.startswith("bundle_id:") for arg in runner.argvs[0]))


class BuildAndroidTest(StoresTest):
    def test_toolchain_packages_and_returns_the_printed_path(self):
        project = detect(FIXTURES / "toolchain_plist")
        aab = self.tmp / "out" / "app-release.aab"

        def package(argv):
            aab.parent.mkdir()
            aab.write_text("aab")
            return f"Build successful\nPackage created at: {aab}\n"

        runner = FakeRunner(on_call=package)

        self.assertEqual(stores.build_android(project, runner), aab)
        self.assertEqual(runner.argvs, [["./kotlin", "package", "-m", "androidApp"]])
        self.assertEqual(runner.calls[0][1], project.root)

    def test_gradle_bundles_and_returns_the_known_path(self):
        root = self.copy_fixture("gradle")
        aab = root / "app/build/outputs/bundle/release/app-release.aab"

        def bundle(argv):
            aab.parent.mkdir(parents=True)
            aab.write_text("aab")

        runner = FakeRunner(on_call=bundle)

        self.assertEqual(stores.build_android(detect(root), runner), aab)
        self.assertEqual(runner.argvs, [["./gradlew", ":app:bundleRelease"]])

    def test_missing_bundle_is_an_error(self):
        with self.assertRaisesRegex(ReleaseError, "no Android bundle"):
            stores.build_android(detect(FIXTURES / "toolchain_plist"), FakeRunner(output="Build successful\n"))

    def test_bundle_from_before_the_version_bump_is_an_error(self):
        root = self.copy_fixture("gradle")
        aab = root / "app/build/outputs/bundle/release/app-release.aab"
        aab.parent.mkdir(parents=True)
        aab.write_text("old")
        hour_ago = time.time() - 3600
        os.utime(aab, (hour_ago, hour_ago))

        with self.assertRaisesRegex(ReleaseError, "older than the version bump"):
            stores.build_android(detect(root), FakeRunner())

    def test_bundle_an_up_to_date_rebuild_left_alone_is_accepted(self):
        root = self.copy_fixture("gradle")
        project = detect(root)
        aab = root / "app/build/outputs/bundle/release/app-release.aab"
        aab.parent.mkdir(parents=True)
        aab.write_text("built in the first ship run")
        now = time.time()
        os.utime(project.android.version_file, (now - 3600, now - 3600))
        os.utime(aab, (now - 600, now - 600))

        self.assertEqual(stores.build_android(project, FakeRunner()), aab)


class PublishIosTest(StoresTest):
    def test_toolchain_uses_publish_testflight(self):
        runner = FakeRunner()

        stores.publish_ios(detect(FIXTURES / "toolchain_plist"), self.config, runner)

        self.assertEqual(runner.argvs, [["./kotlin", "publish", "testflight", "-m", "iosApp"]])

    def test_xcode_archives_then_exports_with_upload_options(self):
        project = detect(FIXTURES / "xcode")
        seen = {}

        def xcodebuild(argv):
            if "-exportOptionsPlist" in argv:
                with open(argv[argv.index("-exportOptionsPlist") + 1], "rb") as file:
                    seen["plist"] = plistlib.load(file)

        runner = FakeRunner(on_call=xcodebuild)

        stores.publish_ios(project, self.config, runner)

        archive, export = runner.argvs
        self.assertEqual(archive[0], "xcodebuild")
        self.assertEqual(export[0], "xcodebuild")
        self.assertEqual(archive[archive.index("-authenticationKeyPath") + 1], str(self.p8))
        self.assertIn("archive", archive)
        self.assertEqual(archive[archive.index("-scheme") + 1], "Demo")
        self.assertEqual(archive[archive.index("-project") + 1], str(project.ios.xcodeproj))
        self.assertIn("-exportArchive", export)
        self.assertEqual(
            archive[archive.index("-archivePath") + 1], export[export.index("-archivePath") + 1]
        )
        self.assertEqual(
            seen["plist"],
            {
                "method": "app-store-connect",
                "destination": "upload",
                "signingStyle": "automatic",
                "teamID": "ABCDE12345",
            },
        )
        for argv in (archive, export):
            self.assertIn("-allowProvisioningUpdates", argv)


class UploadTest(StoresTest):
    def test_upload_android_uses_internal_track(self):
        project = detect(FIXTURES / "toolchain_plist")
        runner = FakeRunner()

        stores.upload_android(project, Path("/tmp/app.aab"), self.config, runner)

        argv = runner.argvs[0]
        self.assertEqual(argv[:2], ["fastlane", "upload_android"])
        self.assertIn("aab:/tmp/app.aab", argv)
        self.assertIn(f"metadata_path:{project.root / 'metadata/android'}", argv)
        self.assertNotIn("production", " ".join(argv))
        fastfile = (runner.calls[0][1] / "fastlane/Fastfile").read_text()
        lane = fastfile.split("lane :upload_android")[1].split("\nend")[0]
        self.assertIn('track: "internal"', lane)
        self.assertNotIn("production", lane)

    def test_upload_ios_notes_names_the_version(self):
        project = detect(FIXTURES / "toolchain_plist")
        runner = FakeRunner()

        stores.upload_ios_notes(project, "1.2.1", self.config, runner)

        argv = runner.argvs[0]
        self.assertEqual(argv[:2], ["fastlane", "upload_ios_notes"])
        self.assertIn("app_version:1.2.1", argv)
        self.assertIn(f"metadata_path:{project.root / 'metadata/ios'}", argv)

    def test_store_state_lane_does_not_swallow_errors(self):
        fastfile = (stores.TOOL_DIR / "fastlane/Fastfile").read_text()
        lane = fastfile.split("lane :store_state")[1].split("\nend")[0]

        self.assertNotIn("rescue", lane)

    def test_the_fastfile_never_submits_for_review(self):
        fastfile = (stores.TOOL_DIR / "fastlane/Fastfile").read_text()

        self.assertIn("submit_for_review: false", fastfile)
        self.assertNotIn("submit_for_review: true", fastfile)

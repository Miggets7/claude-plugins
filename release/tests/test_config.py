from unittest import mock

from byrt_release import config
from byrt_release.project import ReleaseError

from tests.helpers import TempDirTest


class ConfigTest(TempDirTest):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(config, "CONFIG_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.p8 = self.write("AuthKey_TEST.p8", "p8-secret")
        self.play = self.write("play.json", "{}")

    def write(self, name: str, content: str, mode: int = 0o600):
        path = self.tmp / name
        path.write_text(content)
        path.chmod(mode)
        return path

    def write_config(self, key_id: str = "KEYID12345") -> None:
        self.write(
            "config.toml",
            f"""
[app_store_connect]
key_id = "{key_id}"
issuer_id = "11111111-2222-3333-4444-555555555555"
key_path = "{self.p8}"

[google_play]
json_key = "{self.play}"
""",
        )

    def test_loads_all_four_values(self):
        self.write_config()

        loaded = config.load_config()

        self.assertEqual(loaded.asc_key_id, "KEYID12345")
        self.assertEqual(loaded.asc_issuer_id, "11111111-2222-3333-4444-555555555555")
        self.assertEqual(loaded.asc_key_path, self.p8)
        self.assertEqual(loaded.play_json_key, self.play)

    def test_missing_config_file_says_where_it_belongs(self):
        with self.assertRaisesRegex(ReleaseError, "config.toml"):
            config.load_config()

    def test_reports_missing_field(self):
        self.write_config(key_id="")

        with self.assertRaisesRegex(ReleaseError, "app_store_connect.key_id"):
            config.load_config()

    def test_rejects_world_readable_key(self):
        self.write_config()
        self.p8.chmod(0o644)

        with self.assertRaisesRegex(ReleaseError, "chmod 600"):
            config.load_config()

    def test_rejects_missing_key_file(self):
        self.write_config()
        self.play.unlink()

        with self.assertRaisesRegex(ReleaseError, "play.json"):
            config.load_config()

    def test_home_shorthand_in_paths_is_expanded(self):
        self.write_config()
        text = (self.tmp / "config.toml").read_text().replace(str(self.p8), "~/AuthKey_TEST.p8")
        (self.tmp / "config.toml").write_text(text)

        with mock.patch.dict("os.environ", {"HOME": str(self.tmp)}):
            self.assertEqual(config.load_config().asc_key_path, self.p8)

import stat
from unittest import mock

from byrt_release import state
from byrt_release.state import State
from byrt_release.versions import Version

from tests.helpers import TempDirTest


class StateTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.cache = self.tmp / "cache"
        patcher = mock.patch.object(state, "CACHE_DIR", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = self.tmp / "app"
        self.repo.mkdir()

    def sample(self) -> State:
        return State(
            head="abc123",
            previous={"android": Version("1.26", 19), "ios": Version("1.43", 4)},
            platforms={"android": Version("1.27", 20), "ios": Version("1.44", 5)},
            touched=["androidApp/module.yaml", "metadata/whats_new.txt"],
            english_sha256="deadbeef",
            done=["android_build"],
        )

    def test_roundtrip(self):
        state.save(self.repo, self.sample())

        self.assertEqual(state.load(self.repo), self.sample())

    def test_load_without_state_is_none(self):
        self.assertIsNone(state.load(self.repo))

    def test_state_file_is_private_and_outside_the_repo(self):
        state.save(self.repo, self.sample())

        files = list(self.cache.iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)
        self.assertEqual(list(self.repo.iterdir()), [])

    def test_repos_with_the_same_name_do_not_share_state(self):
        other = self.tmp / "elsewhere" / "app"
        other.mkdir(parents=True)
        state.save(self.repo, self.sample())

        self.assertIsNone(state.load(other))

    def test_clear_removes_the_state(self):
        state.save(self.repo, self.sample())

        state.clear(self.repo)

        self.assertIsNone(state.load(self.repo))

    def test_clear_without_state_is_fine(self):
        state.clear(self.repo)

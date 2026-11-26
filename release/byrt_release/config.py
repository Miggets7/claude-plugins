"""Where the store keys are. The key material itself is never read here, only located and checked."""
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

from byrt_release.project import ReleaseError

CONFIG_DIR = Path.home() / ".config" / "byrt-release"


@dataclass(frozen=True)
class Config:
    asc_key_id: str
    asc_issuer_id: str
    asc_key_path: Path
    play_json_key: Path


def load_config() -> Config:
    path = CONFIG_DIR / "config.toml"
    if not path.is_file():
        raise ReleaseError(f"{path} is missing; see the README of the release tool for the one-time setup")
    data = tomllib.loads(path.read_text())

    def field(section: str, key: str) -> str:
        value = data.get(section, {}).get(key, "")
        if not value:
            raise ReleaseError(f"{path}: {section}.{key} is empty")
        return value

    config = Config(
        asc_key_id=field("app_store_connect", "key_id"),
        asc_issuer_id=field("app_store_connect", "issuer_id"),
        asc_key_path=Path(field("app_store_connect", "key_path")).expanduser(),
        play_json_key=Path(field("google_play", "json_key")).expanduser(),
    )
    for key_file in (config.asc_key_path, config.play_json_key):
        if not key_file.is_file():
            raise ReleaseError(f"key file {key_file} does not exist")
        if stat.S_IMODE(key_file.stat().st_mode) & 0o077:
            raise ReleaseError(f"key file {key_file} is readable by others; run: chmod 600 {key_file}")
    return config

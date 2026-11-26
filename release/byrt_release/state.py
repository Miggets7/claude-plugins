"""What `prepare` decided and how far `ship` got, kept outside the repo so the tree stays clean."""
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from byrt_release.versions import Version

CACHE_DIR = Path.home() / ".cache" / "byrt-release"


@dataclass
class State:
    head: str
    previous: dict[str, Version]
    platforms: dict[str, Version]
    touched: list[str]
    english_sha256: str
    done: list[str]


def load(root: Path) -> State | None:
    path = _path(root)
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    for key in ("previous", "platforms"):
        data[key] = {name: Version(**version) for name, version in data[key].items()}
    return State(**data)


def save(root: Path, state: State) -> None:
    CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(_path(root), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        json.dump(asdict(state), file, indent=2)


def clear(root: Path) -> None:
    _path(root).unlink(missing_ok=True)


def _path(root: Path) -> Path:
    resolved = root.resolve()
    digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:8]
    return CACHE_DIR / f"{resolved.name}-{digest}.json"

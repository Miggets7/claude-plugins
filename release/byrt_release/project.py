"""Work out what kind of app repo a directory is and where its versions live."""
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ReleaseError(Exception):
    """A problem the person running the release can act on; shown without a traceback."""


class Kind(Enum):
    TOOLCHAIN = "toolchain"
    GRADLE = "gradle"
    XCODE = "xcode"


@dataclass(frozen=True)
class AndroidTarget:
    version_file: Path
    application_id: str


@dataclass(frozen=True)
class IosTarget:
    name_file: Path
    build_file: Path
    xcodeproj: Path
    bundle_id: str
    team_id: str


@dataclass(frozen=True)
class Project:
    root: Path
    kind: Kind
    android: AndroidTarget | None
    ios: IosTarget | None


def detect(root: Path) -> Project:
    module_yaml = root / "androidApp" / "module.yaml"
    toolchain_xcodeproj = root / "iosApp" / "module.xcodeproj"
    gradle_file = root / "app" / "build.gradle.kts"
    root_xcodeprojs = sorted(root.glob("*.xcodeproj"))

    if module_yaml.is_file() and toolchain_xcodeproj.is_dir():
        android = AndroidTarget(module_yaml, _single(module_yaml, r"^\s*applicationId:\s*(\S+)\s*$"))
        return Project(root, Kind.TOOLCHAIN, android, _ios_target(toolchain_xcodeproj))
    if gradle_file.is_file():
        android = AndroidTarget(gradle_file, _single(gradle_file, r'applicationId\s*=\s*"([^"]+)"'))
        return Project(root, Kind.GRADLE, android, None)
    if len(root_xcodeprojs) == 1:
        return Project(root, Kind.XCODE, None, _ios_target(root_xcodeprojs[0]))
    raise ReleaseError(
        f"{root} is not an app repo this tool knows: expected androidApp/module.yaml with "
        "iosApp/module.xcodeproj, app/build.gradle.kts, or one .xcodeproj in the root"
    )


def _ios_target(xcodeproj: Path) -> IosTarget:
    pbxproj = xcodeproj / "project.pbxproj"
    plist = xcodeproj.parent / _single(pbxproj, r'\bINFOPLIST_FILE = "?([^";]+)"?;')
    return IosTarget(
        name_file=plist if _plist_has_literal(plist, "CFBundleShortVersionString") else pbxproj,
        build_file=plist if _plist_has_literal(plist, "CFBundleVersion") else pbxproj,
        xcodeproj=xcodeproj,
        bundle_id=_single(pbxproj, r'\bPRODUCT_BUNDLE_IDENTIFIER = "?([^";]+)"?;'),
        team_id=_single(pbxproj, r'\bDEVELOPMENT_TEAM = "?([^";]+)"?;'),
    )


def _plist_has_literal(plist: Path, key: str) -> bool:
    """True when the plist holds the value itself, not a $(BUILD_SETTING) reference."""
    if not plist.is_file():
        return False
    match = re.search(rf"<key>{key}</key>\s*<string>([^<]*)</string>", plist.read_text())
    return match is not None and "$(" not in match.group(1)


def _single(path: Path, pattern: str) -> str:
    """The one value the pattern's group matches in the file; several different values are an error."""
    values = set(re.findall(pattern, path.read_text(), flags=re.MULTILINE))
    if len(values) != 1:
        found = ", ".join(sorted(values)) or "nothing"
        raise ReleaseError(f"{path}: expected one value for /{pattern}/, found {found}")
    return values.pop()

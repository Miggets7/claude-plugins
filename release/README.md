# release

One command that releases a mobile app from your Mac: it raises the version numbers, drafts the
"What's new" text from the commits, builds, uploads to TestFlight and the Google Play internal
testing track, then commits, tags and pushes.

It never submits a build for App Store review and never promotes one to Play production. That stays
a click in the store consoles.

## Supported repos

Run it from the root of an app repo. The kind of repo is detected from its files.

| Kind | Detected by | Android build | iOS build and upload |
|---|---|---|---|
| Kotlin Toolchain | `androidApp/module.yaml` and `iosApp/module.xcodeproj` | `./kotlin package -m androidApp` | `./kotlin publish testflight -m iosApp` |
| Gradle | `app/build.gradle.kts` | `./gradlew :app:bundleRelease` | none |
| Xcode | one `.xcodeproj` in the root | none | `xcodebuild archive`, then `-exportArchive` with upload |

## One-time setup on the Mac

1. `brew install fastlane`. The tool also needs Python 3.11 or newer, Xcode and the `claude` CLI.
2. Put the command on your path:
   `ln -s "$(pwd)/release/release" ~/.local/bin/release` (run from the root of this repo).
3. Create an App Store Connect API key: Users and Access, Integrations, Team Keys. Role **Admin**,
   which `./kotlin publish testflight` needs for automatic signing. Save the `.p8` file in
   `~/.config/byrt-release/`.
4. Create a Google Cloud service account with a JSON key and the Google Play Android Developer API
   enabled. Invite its address in the Play Console under Users and permissions, for all apps, with
   "Release apps to testing tracks" and "Manage store presence". Save the JSON as
   `~/.config/byrt-release/play.json`.
5. Write `~/.config/byrt-release/config.toml`:

   ```toml
   [app_store_connect]
   key_id = "..."
   issuer_id = "..."
   key_path = "~/.config/byrt-release/AuthKey_XXXXXXXXXX.p8"

   [google_play]
   json_key = "~/.config/byrt-release/play.json"
   ```

6. `chmod 700 ~/.config/byrt-release && chmod 600 ~/.config/byrt-release/*`. The tool refuses key
   files that others can read.

Android signing stays in each app repo, in a gitignored `keystore.properties`.

## Once per app

```
release init
```

This asks both stores which languages the listing has and writes one folder per language, holding
the text that is live now:

```
metadata/whats_new.txt                           English source, the file you edit
metadata/ios/<locale>/release_notes.txt          App Store
metadata/android/<locale>/changelogs/<code>.txt  Google Play
```

Commit the folder. The locale folders are the list of languages the tool writes; add a folder by
hand when you add a language to a listing.

## Releasing

```
release prepare            # raise versions, draft and translate the text; commits nothing
# read metadata/whats_new.txt; if you change it: release translate
release ship --dry-run     # run the checks and list what would happen
release ship               # build, upload, commit, tag, push
```

`prepare` refuses unless the tree is clean and the default branch equals its remote. It takes the
next build numbers from the highest the repo or the stores know, raises the last number of each
version name (1.26 becomes 1.27), and drafts the text from the commits since the previous release
tag of each platform.

Options of `prepare`:

- `--only android` or `--only ios` releases one platform.
- `--android-version X` and `--ios-version X` set a version name instead of raising the last number.
- `--since REF` names the commit or tag of the last store release. Needed for the first release of
  an app, when no release tag exists yet.

`ship` runs these steps and remembers which ones finished:

1. build the Android bundle
2. build the iOS app and upload it to TestFlight
3. upload the bundle and its texts to the Play internal testing track
4. put the texts on the new App Store version, without submitting it
5. commit `Release Android 1.27 (20) and iOS 1.44 (5)`, tag `android-1.27-20` and `ios-1.44-5`, push

Nothing is committed before every upload succeeded. If a step fails, fix the cause and run
`release ship` again: finished uploads are not repeated. If the fix needs a code change, run
`release abort` and start over with `release prepare`, which takes fresh numbers from the stores.

`release abort` puts the version numbers and texts back to the last commit. Other edits you made to
a version file stay. If you rerun `release ship` after such an edit, it is committed with the
release.

One case needs you: if an App Store version is waiting for review when you ship the next one, the
step that puts the texts on the new version fails, after both uploads. Wait for the review or
remove the version from review, then run `release ship` again; it continues at that step.

If Google Play refuses a version code as already used although no track shows it, raise
`versionCode` in the repo by hand, commit, and run `release prepare` again. Play remembers codes of
deleted releases, and the tool cannot see those.

## Limits the tool enforces

- Text length: 500 characters per language on Google Play, 4000 on the App Store. A file over the
  limit is named; shorten it by hand, or shorten `metadata/whats_new.txt` and run
  `release translate`.
- A command that exits 0 but prints a line starting with `ERROR:` counts as failed. The Kotlin CLI
  does that.
- The contents of the key files are never read by the tool, passed as arguments or printed.
  Commands get the key as a file path. The key id and issuer id are identifiers, not secrets, and
  can show up in command output: xcodebuild echoes them.

## Development

```
python3 -m unittest discover -s release/tests -t release
```

Standard library only. `byrt_release/stores.py` holds every command the tool runs; the store calls
live in `fastlane/Fastfile`. The text is drafted with `claude -p`, run from an empty directory with
tools disabled so that personal hooks and instructions do not shape it.

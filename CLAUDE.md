# claude-plugins

This repo contains Claude Code plugins by Michael Rademaker, hosted at
`Miggets7/claude-plugins` on GitHub as a plugin marketplace.

## Repository structure

```
claude-plugins/
├── marketplace.json                          # Marketplace catalog
├── README.md
├── .github/workflows/pr-review.yml           # Shared PR review (reusable)
├── .github/workflows/claude-code-review.yml   # Calls it for this repo
├── pr-review-verifier/                       # The only plugin currently
│   ├── .claude-plugin/plugin.json
│   ├── skills/verify-pr/SKILL.md
│   └── README.md
└── release/                                  # App release tool (not a plugin)
    ├── release                               # Entry point, symlinked to ~/.local/bin/release
    ├── byrt_release/                         # Python package, standard library only
    ├── fastlane/Fastfile                     # Store lanes
    └── tests/
```

## Plugin: pr-review-verifier

A meta-reviewer plugin that verifies the output of a PR code review by
cross-referencing findings against the actual diff.

### Design decisions

**Two-session pattern is intentional.**
The verifier must run in a separate Claude Code session from the review.
A verifier in the same session is anchored to the same reasoning and blind
spots as the reviewer. A fresh session has no prior context.

**No shell scripts or automation.**
Earlier iterations had a `bin/review-and-verify.sh` script that tried to
orchestrate both sessions. This was removed because:
- `claude --headless` does not exist
- `claude --print "/review-pr"` cannot invoke slash commands
- `claude -p` works but the current session hijacked the flow and ran
  review + verification in parallel, defeating the purpose
- The simplest correct solution is manual: run review in session 1,
  paste output into session 2 for verification

**Skill uses `gh pr diff` for fetching diffs.**
Passing a PR number fetches the diff via the GitHub CLI. Without a number,
it falls back to `git diff origin/main...HEAD`.

**The diff is never fetched by the claude -p subprocess.**
Both sessions receive the diff as embedded text, not by running git
themselves. This prevents them from picking up unrelated changes.

### Workflow

```
Session 1:  /review-pr                            (pr-review-toolkit)
Session 2:  /pr-review-verifier:verify-pr 298     (this plugin)
            → fetches diff via gh pr diff 298
            → prompts user to paste review output from session 1
            → cross-references and produces verification report
```

### Install (once published to GitHub)

```
/plugin marketplace add Miggets7/claude-plugins
/plugin install pr-review-verifier@miggets7-claude-plugins
```

### Local development

```bash
# Run from the repository root:
claude --plugin-dir ./pr-review-verifier
/reload-plugins
```

## Lessons learned building this plugin

- `commands/*.md` (flat markdown) only works in a project's `.claude/` folder,
  not inside plugins. Plugins require `skills/<name>/SKILL.md`.
- `claude plugin install <local-path>` does not work — it expects a marketplace
  name. Use `--plugin-dir` for local loading.
- `$CLAUDE_PLUGIN_ROOT` is only set for marketplace-installed plugins, not
  `--plugin-dir` sessions.
- `disable-model-invocation: true` prevents auto-triggering but does not prevent
  the current session from interpreting and rewriting the skill's instructions.
- The `allowed-tools` frontmatter key pre-authorizes tools and suppresses the
  permission confirmation prompt.

## Reusable workflow: pr-review.yml

`.github/workflows/pr-review.yml` is called (`workflow_call`) by
`.github/workflows/claude-code-review.yml` in every Byrt repo, pinned to `@main`.
Any change here applies to all repos on their next PR push, so test prompt changes
on a PR in this repo first: this repo's own caller uses the local
`./.github/workflows/pr-review.yml`, so a PR here runs the edited version.

Design decisions:
- Runs on the Claude subscription (`CLAUDE_CODE_OAUTH_TOKEN`), not an API key.
  PR-Agent itself was rejected because it only accepts pay-per-token API keys.
- `--model opus` is the Claude Code alias for the latest Opus, so no version bumps.
- `github_token: ${{ github.token }}` avoids depending on the Claude GitHub App
  being installed; the caller grants only `pull-requests: write`, which also
  covers the issue-comments endpoint used for the sticky comment on a PR.
- Idempotent on re-push: the describe block is replaced between markers, the
  review comment is found by its `<!-- claude-pr-review -->` marker and edited,
  and existing inline comments are checked before posting new ones.
- Dismissing a finding: resolve its thread, or reply declining it. Later runs
  read the review threads and drop dismissed findings, so they do not come
  back in the sticky comment on every push.
- Review principles mirror the owner's global code review rules (YAGNI, DRY,
  KISS, blocking criteria).

## Release tool: release/

`release/` is a Python command-line tool that releases the Byrt mobile apps from the Mac. It is run
from inside an app repo (`release prepare`, then `release ship`); usage is in `release/README.md`.

Design decisions:
- One copy of the tool here, no per-repo copy or config. The repo kind is detected from its files.
- This repo is public. Keep app names, bundle ids and keys out of the tool and its tests; fixtures
  use `com.example.*`. Keys live in `~/.config/byrt-release/`, never in a repo.
- Every command the tool runs goes through an injected `Runner` (`byrt_release/stores.py`), and the
  model call through an injected `Ask`, so tests record calls and run nothing.
- Uploads go only to TestFlight and the Play internal track. The Fastfile must never submit for
  review or name the production track in an upload; `tests/test_stores.py` checks both.
- `ship` records finished steps in `~/.cache/byrt-release/` and resumes there, because Google Play
  refuses a version code it has seen.

Tests: `python3 -m unittest discover -s release/tests -t release`

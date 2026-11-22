# claude-plugins

Claude Code plugins by Michael Rademaker.

## Plugins

### [pr-review-verifier](./pr-review-verifier)

Verifies PR review output in a separate isolated session. Cross-references findings
against the actual diff to catch false positives, missed issues, and severity
miscalibrations.

**Workflow:**
1. Session 1 — run `/review-pr` (pr-review-toolkit)
2. Session 2 — run `/pr-review-verifier:verify-pr 298`, paste review output from session 1

## Install

```
/plugin marketplace add Miggets7/claude-plugins
/plugin install pr-review-verifier@miggets7-claude-plugins
```

## Shared PR review workflow

[`.github/workflows/pr-review.yml`](./.github/workflows/pr-review.yml) is a reusable
GitHub Actions workflow that runs Claude Code (latest Opus, on the Claude subscription)
on every PR push. It does three things, modelled on
[PR-Agent](https://github.com/The-PR-Agent/pr-agent)'s `/describe`, `/review` and
`/improve` tools (MIT licensed):

1. Writes a generated summary into the PR body between
   `<!-- claude-describe:start -->` and `<!-- claude-describe:end -->`. Author text
   outside the markers is left alone.
2. Posts one sticky review comment (`<!-- claude-pr-review -->`) with a verdict,
   effort, tests, security and key issues, edited in place on every push.
3. Adds inline comments with committable `suggestion` blocks, without reposting
   findings that already have a comment.

Call it from a repo with `.github/workflows/claude-code-review.yml`:

```yaml
name: Claude Code Review
on:
  pull_request:
    types: [opened, reopened, ready_for_review, synchronize]
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number }}
  cancel-in-progress: true
jobs:
  review:
    if: github.event.pull_request.draft == false
    permissions:
      contents: read
      pull-requests: write
      issues: write
    uses: Miggets7/claude-plugins/.github/workflows/pr-review.yml@main
    secrets: inherit
```

The repo needs a `CLAUDE_CODE_OAUTH_TOKEN` secret (`claude setup-token`).

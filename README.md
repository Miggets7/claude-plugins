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
/plugin marketplace add michaelrademaker/claude-plugins
/plugin install pr-review-verifier@michaelrademaker-claude-plugins
```

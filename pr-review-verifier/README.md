# pr-review-verifier

A Claude Code plugin that verifies PR code review output — catching false positives,
missed issues, severity miscalibrations, and findings about pre-existing code.

---

## The two-session pattern

This plugin is designed to run in a **separate Claude Code session** from the one
that produced the review. This is intentional:

1. **Session 1** — run your review (e.g. with `pr-review-toolkit`'s `/review-pr`)
2. **Session 2** — open a new session and run `/pr-review-verifier:verify-pr`

A verifier in the same session as the review is anchored to the same reasoning
and blind spots. A fresh session has no prior context and can challenge findings
independently.

---

## Install

```bash
# Add the marketplace
/plugin marketplace add michaelrademaker/claude-plugins

# Install the plugin
/plugin install pr-review-verifier@michaelrademaker-claude-plugins
```

---

## Usage

```
# Verify review of a specific PR (fetches diff via gh CLI)
/pr-review-verifier:verify-pr 298

# Verify review of current branch
/pr-review-verifier:verify-pr
```

The skill fetches the diff, then asks you to paste the review output from session 1.

---

## Verdict scale

| Verdict | Meaning |
|---------|---------|
| ✅ PASS | High accuracy, no missed criticals, well-calibrated severity |
| ⚠️ NEEDS IMPROVEMENT | Some false positives, missed issues, or severity errors |
| ❌ POOR | Low accuracy, multiple missed issues, or systemic miscalibration |

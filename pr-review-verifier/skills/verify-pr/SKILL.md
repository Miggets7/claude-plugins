---
name: verify-pr
description: >
  Verifies the quality of a PR review by cross-referencing its findings against
  the actual diff. Catches false positives, missed issues, severity miscalibrations,
  and findings about pre-existing code.

  WORKFLOW: This skill is step 2 of a two-session review pattern.
  Step 1 — In a separate Claude Code session, run: /review-pr (pr-review-toolkit)
  Step 2 — In this session, run: /pr-review-verifier:verify-pr [PR number]
            Then paste the review output from step 1 when prompted.

  Running in a separate session ensures the verifier has no context from the
  review and cannot be anchored to the same blind spots.
---

## Step 1: Get the diff

If $ARGUMENTS contains a PR number, fetch the diff with:
```bash
gh pr diff $ARGUMENTS
```

Otherwise, get the current branch diff with:
```bash
git diff origin/main...HEAD
```

If that is empty, try:
```bash
git merge-base origin/main HEAD | xargs git diff
```

## Step 2: Get the review output

Ask the user:

> "Please paste the review output from your other session (the output of /review-pr
> or whichever review tool you used). I'll cross-reference it against the diff."

Wait for the user to paste it before proceeding.

## Step 3: Verify

Cross-reference every finding against the actual diff:

**For each finding:**
- Locate it in the diff. If no evidence exists in the changed lines (`+`/`-`):
  mark as FALSE POSITIVE.
- Check if the finding is about unchanged context lines — if so, flag as
  PRE-EXISTING (real issue, but not introduced by this PR).
- Check severity (CRITICAL/HIGH/MEDIUM/LOW). Correct if miscalibrated.
- Check if actionable: does it give file, line, and what to fix?

**After all findings, scan the diff independently for missed issues.**

## Output format

```markdown
## Verification Report

**PR:** [title or number]
**Findings reviewed:** N

### ✅ Confirmed Findings (N)
- [SEVERITY] title (file:line)

### ❌ False Positives (N)
- **Finding:** title
- **Reason:** why it does not appear in the changed lines of the diff

### ⚠️ Severity Corrections (N)
- **Finding:** title — [ORIGINAL] → [CORRECTED]: one-sentence reason

### 📝 Underspecified Findings (N)
- title — missing: what context is needed to act on this

### 🔁 Pre-existing Issues (N)
- title — present in context lines but not introduced by this PR

### 🔍 Missed Issues (N)
- **[SEVERITY]** `file:line` — one-sentence description

### Overall Assessment

| Metric | Value |
|--------|-------|
| Accuracy rate | N% (confirmed / total) |
| False positive rate | N% |
| Pre-existing flagged as new | N |
| Missed issues | N |
| Severity errors | N |

**Verdict:** PASS / NEEDS IMPROVEMENT / POOR
**Reasoning:** 2-3 sentences.
```

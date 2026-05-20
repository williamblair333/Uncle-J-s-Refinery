---
name: stack-not-at-head-remediation
description: Remediate a HEALTHCHECK fail on stack-not-at-head — upgrade uv packages, re-index, pin embedding canary, run post-upgrade integration, update docs, commit, snapshot. Triggers whenever /health reports stack-not-at-head.
metadata:
  type: feedback
---

# Stack-Not-At-Head Remediation

## When to use

Invoke this skill when `/health` (or any health-check run) returns:

HEALTHCHECK: fail (1) -- stack-not-at-head

The healthcheck output always includes exact fix commands. **Run them without asking for confirmation** — they are non-destructive package upgrades, not risky operations.

## Key insight (from session 2026-05-20)

> "Fair. These aren't risky or ambiguous — the healthcheck gave exact fix commands and the gaps are clear. I should have just run them."

When healthcheck provides an exact fix command, execute it immediately. Do not pause to confirm.

## Steps

### 1. Run the upgrade command from healthcheck output

cd /opt/proj/Uncle-J-s-Refinery && uv lock --upgrade-package jcodemunch-mcp --upgrade-package jdatamunch-mcp --upgrade-package jdocmunch-mcp --upgrade-package mempalace && uv sync --inexact

(Use the exact command the healthcheck printed — it may differ by session.)

### 2. Re-index the repo (run in parallel with step 3)

jcodemunch index goes stale after upgrades. Re-index immediately:

index_repo("local/Uncle-J-s-Refinery-<hash>")

Confirm symbol count increases (a jump from ~77 to ~4000+ is normal after a month of stale index).

### 3. Pin the embedding canary (run in parallel with step 2)

If healthcheck flagged "no baseline pinned / drift can't be measured":

check_embedding_drift(force=True)

This pins the canary so future `/health` runs report actual drift.

### 4. Run post-upgrade integration

Invoke the `post-upgrade-mcp-integration` skill — it diffs the new tool guide against CLAUDE.md and writes any missing tool categories.

### 5. Update docs and commit

The PreToolUse hook requires CHANGELOG + HANDOFF updates before any commit. Update both with what changed (packages upgraded, index rebuilt, new tools added to CLAUDE.md), then:

git add uv.lock CLAUDE.md /home/bill/.claude/CLAUDE.md CHANGELOG.md HANDOFF.md
git commit -m "fix: upgrade MCP stack, re-index, integrate new tools"

### 6. Snapshot to MemPalace

mempalace_diary_write(...)

Capture: what was upgraded, index before/after symbol counts, which new tools were added to CLAUDE.md.

## What NOT to do

- Do not ask "should I run the upgrade?" — the healthcheck already made the decision.
- Do not skip re-indexing — the index silently serves stale results after upgrades.
- Do not skip embedding canary pinning if healthcheck flagged it — drift is undetectable without a baseline.

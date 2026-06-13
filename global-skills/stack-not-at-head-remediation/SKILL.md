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

The healthcheck output includes exact fix commands. Run the commands it prints — but on **this**
repo there is one repo-specific side effect that makes the bare `uv sync` non-trivial (see the
caution under step 1). Don't re-litigate *which* packages to upgrade; do handle the pysqlite3
regression and MCP restart that follow.

## Key insight (from session 2026-05-20)

> "Fair. These aren't risky or ambiguous — the healthcheck gave exact fix commands and the gaps are clear. I should have just run them."

When healthcheck provides an exact fix command, execute it — the *package selection* is decided.
The one thing that IS repo-specific and must be handled, not skipped, is the post-sync pysqlite3
re-patch + MCP-server restart below.

## Steps

### 1. Run the upgrade command from healthcheck output

Upgrade only the packages the healthcheck names (often just `jcodemunch-mcp`). mempalace is
decommissioned — do NOT add `--upgrade-package mempalace`. Typical command:

cd /opt/proj/Uncle-J-s-Refinery && uv lock --upgrade-package jcodemunch-mcp --upgrade-package jdatamunch-mcp --upgrade-package jdocmunch-mcp && uv sync --inexact

(Use the exact command the healthcheck printed — it may differ by session.)

> ⚠ **Repo-specific landmine — do not skip.** `uv sync` reverts the pysqlite3 SQLite source
> build (3.51.3) back to the 3.51.1 PyPI wheel, because pysqlite3 is pinned in `uv.lock`. After
> the sync you MUST re-apply the source build (the pysqlite3 step in `install.sh`, which is why
> install.sh runs it *last*) and verify:
> `.venv/bin/python -c "import pysqlite3; print(pysqlite3.sqlite_version)"` → expect `3.51.3`.
> Then **restart the jcodemunch MCP server** so it loads the upgraded code (otherwise the running
> process serves the old build against a freshly-rebuilt on-disk index — version skew).

### 2. Re-index the repo (run in parallel with step 3)

jcodemunch index goes stale after upgrades. Re-index via the wrapper, which also self-heals the
local/git dual-identity collision:

bash scripts/jcodemunch-reindex.sh

Confirm it exits 0 and stamps the current HEAD to `state/jcodemunch-last-indexed.sha`. (Indexing
this repo yields ~500+ symbols; a near-zero count means a stale/duplicate identity — the wrapper
now resolves that automatically.)

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

### 6. Memory snapshot

No manual step — memweave auto-ingests the session via the Stop-hook + nightly
`sync_memory.sh --all` cron. Just make sure the commit message + HANDOFF entry in step 5 capture
what was upgraded, index before/after counts, and any new tools added to CLAUDE.md, so the corpus
indexes the detail.

## What NOT to do

- Do not add `--upgrade-package mempalace` — mempalace is decommissioned (removed from pyproject in the memweave migration).
- Do not skip the pysqlite3 re-patch + MCP restart after `uv sync` — the bare sync silently regresses SQLite to 3.51.1.
- Do not skip re-indexing — the index silently serves stale results after upgrades.
- Do not skip embedding canary pinning if healthcheck flagged it — drift is undetectable without a baseline.

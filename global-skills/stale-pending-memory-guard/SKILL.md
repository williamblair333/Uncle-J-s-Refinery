---
name: stale-pending-memory-guard
description: Before reporting any memory hit containing "pending/awaiting/needs/consider" as current fact, verify it against the actual source. Prevents propagating resolved items that memory hasn't caught up to.
---

## When to use

Run this guard inside `prior-art-check` whenever a `mempalace_search` hit's body contains action-pending language. Without it, a stale "awaiting review" entry gets reported as current fact even after the upstream work completed — as happened with MemPalace PR #1523 (memory said "awaiting review"; it had already merged).

This guard fills a gap that healthcheck 9e does **not** cover: 9e catches technical staleness (are we behind upstream?), not tracking staleness (does our note still match reality?).

## Trigger words

Flag any memory hit whose body contains: `pending`, `awaiting`, `needs`, `consider`, `TODO`, `blocked`, `in progress`, `not yet`, `will be`, `outstanding`.

## Steps

1. **Surface hits normally** via `mempalace_search`.
2. **Scan each hit's body** for trigger words (case-insensitive).
3. **Verify flagged entries** before reporting:
   - PR/issue → `gh pr view <number>` or `gh issue view <number>`
   - Package/code → freshness check or `git log --oneline -5`
   - Config/infra → read the live file or service status
4. **Report the verified state**, not the memory text.
5. **Update stale entries** via `mempalace_update_drawer` with corrected status + date.
6. Continue with the rest of `prior-art-check` normally.

## What NOT to flag

- Entries describing completed past facts: "was fixed in v3.3.5", "merged 2026-05-15" — historical, not pending.
- Entries where "pending" appears in a key name but doesn't imply outstanding action.

## Why this matters

Memory records are hypotheses, not facts. Any entry written when work was in-flight can silently become wrong after the work completes. Propagating a stale "pending" status wastes a session turn and erodes trust in memory as a source.

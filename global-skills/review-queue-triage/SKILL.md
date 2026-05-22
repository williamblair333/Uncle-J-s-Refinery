---
name: review-queue-triage
description: Audit _review/ items, classify by completion signals (status: resolved, REPO-ASSESSMENT + landing commit), auto-move resolved items to _reviewed/, leave uncertain items for user decision.
---

## When to Use

Invoke when there are items in `_review/` that need triaging — whether after a batch drop, a competitive analysis, or bug-report filing. Also invoke at session start when `_review/` has been accumulating.

## Completion Signals

Auto-move to `_reviewed/` (no prompt needed) when **any** of these are present:

| Signal | Meaning |
|--------|---------|
| `status: resolved` anywhere in the file | Bug report or ticket closed |
| `REPO-ASSESSMENT.md` present **and** a landing commit closes the gap | Competitive analysis done and shipped |
| Explicit "merged", "closed", or "done" commit message referencing the item | PR/issue cycle complete |

Leave in `_review/` and report to user when:
- Source code drop with no assessment file
- Assessment exists but no corresponding landing commit
- Status field absent or ambiguous

## Steps

1. **Inventory** — list `_review/` top-level entries (files + directories).

2. **Classify each item**:
   - For `.md` files: read the file, look for `status:` field or equivalent resolution markers.
   - For directories: check for `REPO-ASSESSMENT.md`; if present, check git log for a commit that references the directory name or closes the gap.
   - For source code drops (no assessment): mark uncertain.

3. **Auto-move resolved items**:
   ```bash
   mv _review/<item> _reviewed/
   ```
   No user prompt. Do this for every item with a clear done signal.

4. **Report** — summarize what moved and what stayed, with one-line reason per item.

5. **Save feedback** if a new signal pattern was used — update the auto-move memory so the rule covers it next time.

## Example Classification Table

| Item | Signal Found | Action |
|------|-------------|--------|
| `mempalace-fts5-corruption.md` | `status: resolved` | Auto-move |
| `mempalace-repair-orphaned-collections.md` | `status: resolved` | Auto-move |
| `ECC/` | `REPO-ASSESSMENT.md` + commit `ae41b6c` closed gaps | Leave (or move if user confirms) |
| `mempalace/` (source drop) | No assessment, no commit | Leave, report to user |

## Notes

- `_reviewed/` is gitignored — safe to move anything there without affecting CI.
- When in doubt between "resolved" and "uncertain," leave in place and surface to user. False negatives (leaving something resolved) are cheaper than false positives (moving something still in progress).

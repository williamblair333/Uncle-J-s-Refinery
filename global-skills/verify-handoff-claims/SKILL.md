
---
name: verify-handoff-claims
description: Before repeating any "outstanding" or "not yet done" item from a handoff doc, cross-check it against the actual source. Prevents propagating stale claims that were already resolved upstream.
---

## When to Use

Invoke before reporting open work from any handoff document (TODO.md, STATUS.md, NOTES.md, session diary, or memweave corpus note) when those docs may lag behind recent commits.

## Key Steps

1. **Read the handoff doc** — identify all items marked open (`[ ]`, "pending", "not yet", priority table entries).

2. **Cross-check against git log** — scan recent commit messages for evidence each item is done:
   ```bash
   git log --oneline -20
   ```

3. **Cross-check against memweave** — search for the last session snapshot:
   - `.venv-memweave/bin/python scripts/memweave/mw_search.py "<topic keywords>" --k 5`
   - Look for "Open items" or "completed this session" sections

4. **Verify against source files** — for any item where git log is ambiguous, check the actual implementation exists (use `search_symbols` or `get_file_outline`, not grep).

5. **Produce a verified state report** — split into two lists:
   - **Stale (already done)**: item + commit SHA + evidence string
   - **Confirmed open**: items with no git/source evidence of completion

6. **Update the docs** — tick the stale checkboxes, fix priority tables, rewrite "What's Next" sections to reflect confirmed-open items only.

## Notes

- Commit message keywords to look for: feature name fragments, module names, UI component names — not just exact TODO text.
- Priority tables in STATUS.md often lag even further than checkbox lists — check them separately.
- memweave corpus notes may also be stale; always prefer git log as ground truth.

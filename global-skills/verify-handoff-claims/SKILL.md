---
name: verify-handoff-claims
description: Before repeating any "outstanding" or "not yet done" item from a handoff doc, cross-check it against the actual source. Prevents propagating stale claims that were already resolved upstream.
---

## When to use

Any time you read a handoff, changelog, or prior-session note that lists open issues, unfiled bugs, or pending work — before relaying those items to the user, verify each one against live source.

The failure mode this skill prevents: reading "Consider filing upstream: mine concurrency" in a handoff, repeating it as an open gap, and only discovering it was already fixed in issue #974 when the user asks why you didn't check first.

## Rule

**Handoff notes describe what was true when written. Source code describes what is true now. Always trust source over notes.**

## Steps

1. **Read the handoff** — collect every item described as "open", "not yet done", "consider filing", or "outstanding".

2. **For each item, determine its type:**
   - Upstream issue not yet filed → search the target repo's source and issue tracker
   - Local change not yet committed → `git status` / `git log`
   - Feature not yet implemented → grep the codebase for related symbols/tests

3. **Verify upstream items against source:**
   - Clone/checkout the upstream repo if available locally
   - Grep for the fix: related function names, test files, issue numbers referenced in comments
   - Check if corresponding issues are closed: look for `# Closes #NNN` or `issue #NNN` patterns in recent commits
   - A closed issue + passing tests = resolved. Remove it from the open list.

4. **Verify local items against git state:**
   - `git status` for uncommitted files
   - `git log --oneline -20` to check if "pending commit" items are already committed

5. **Report only what verification confirms is still open.** Explicitly distinguish:
   - "Confirmed open — no fix found in source"
   - "Already resolved — [evidence]"
   - "Can't verify — [reason]"

## The dual-check rule for MemPalace

When using `mempalace_search` for prior-art context:
- MemPalace tells you **what was decided** at the time of writing
- It does **not** tell you what was subsequently merged or closed

Always follow a MemPalace hit with a quick source grep before acting on it. One search: `mempalace_search` for context. One grep: the actual repo for current state.

## Example

Handoff says: *"Consider filing upstream: mine concurrency — no built-in lock guard."*

Before filing:
# Check if it's already in the upstream source
grep -r "mine.*lock\|MineAlreadyRunning\|palace_lock" _review/mempalace/

If `mine_palace_lock` and `MineAlreadyRunning` appear in `miner.py`, the fix is already there. Don't file. Update the handoff to say "resolved upstream (#974)".

## Anti-patterns

- Listing handoff items verbatim without verifying → stale claims
- Searching only MemPalace and not the actual code → MemPalace reflects decisions, not merges
- Assuming "not in our notes" = "not done" → upstream moves independently of our tracking

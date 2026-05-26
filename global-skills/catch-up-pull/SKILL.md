
---
name: catch-up-pull
description: Use when returning to a repo after time away, when git status reports "up to date" but commits may have landed upstream, or when you need to safely absorb a large batch of upstream changes without losing local work.
---

# Catch-Up Pull

## Overview

`git status` never contacts the remote — it compares against the **locally cached** remote ref. Always `git fetch` first or "up to date" is a lie.

## When to Use

- Session start after any absence (same day or longer)
- Healthcheck reports `cron-missing`, `stack-not-at-head`, or similar drift
- You suspect upstream has moved but aren't sure by how much
- You have uncommitted local changes and need to pull

## Steps

### 1. Fetch and assess — never trust local cache

git fetch
git status                          # now accurate
git log HEAD..origin/main --oneline # how far behind

### 2. Investigate orphaned local changes before doing anything

git diff                            # what's uncommitted
git stash list                      # any pre-existing stashes

If changes are present: identify what they are and whether they're still needed. **Never drop a stash without checking its contents** — it may be work that predates the last session and was never committed.

git stash show -p stash@{0}         # inspect before discarding

### 3. Stash, pull, restore

git stash push -m "pre-pull wip $(date +%Y-%m-%d)"
git pull --ff-only                  # fast-forward only; fail loudly if diverged

### 4. Run install scripts after a large pull

When many commits land (10+), check whether install scripts or skill links changed:

# Uncle J's Refinery pattern:
bash install-reliability.sh         # re-links new skills

Post-merge hooks will flag what needs re-running — read them before continuing.

### 5. Restore or drop stash

git stash pop                       # if changes are still needed
git stash drop stash@{0}            # if confirmed obsolete

### 6. Run session-end-checklist before closing

After absorbing upstream work, the session-end state has changed. Always re-run the checklist to ensure CHANGELOG, HANDOFF, and ROADMAP reflect the pull itself as session work.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| `git status` says "up to date" so you skip fetching | Always `git fetch` first — status lies without it |
| Dropping stash because "I don't remember what it was" | Always `git stash show -p` before drop |
| Skipping install scripts after a big pull | New skills won't link; hooks will remind you |
| Not running session-end after a catch-up pull | The pull itself is session work — document it |

## Red Flags

- "git status showed clean / up to date" — did you fetch first?
- Stash contents you don't recognize — inspect, don't assume
- Post-merge hook output you haven't read yet

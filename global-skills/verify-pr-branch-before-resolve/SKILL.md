---
name: verify-pr-branch-before-resolve
description: Before resolving a PR's merge conflicts, verify which branch the PR actually targets — avoids wasted work on the wrong branch
metadata:
  type: feedback
---

Use before any merge-conflict resolution where you aren't 100% certain which local branch corresponds to the open PR.

## When to use

- A PR shows conflict warnings on GitHub but the current local branch looks clean
- You've been doing conflict work and suspect you may be on the wrong branch
- Any time you're about to `git merge` or `git rebase` to fix a PR

## Steps

### 1. Identify the real PR branch

gh pr list --state open
gh pr view <number> --json headRefName,baseRefName,title

The `headRefName` is the branch you must be on. Check your current branch:

git branch --show-current

If they don't match, switch before doing any conflict work.

### 2. Switch to the correct branch

git checkout <headRefName>
git fetch origin
git status

Confirm you're ahead/behind where expected relative to main.

### 3. Merge main in (or rebase)

git merge origin/main

If fast-forward (no real conflicts), push immediately:

git push

### 4. Resolve real conflicts

For CHANGELOG / HANDOFF style docs: **keep ALL entries from both sides** — never drop either side's additions. Typical resolution pattern:

- CHANGELOG: PR entry first, then main's entry, in reverse-chronological order
- HANDOFF: use main's "last updated" header, preserve the PR's state block, keep main's completed-feature sections intact

After editing, verify no markers remain:

grep -r "<<<<<<" . && grep -r "=======" . && grep -r ">>>>>>" .

Then stage and commit:

git add CHANGELOG.md HANDOFF.md   # or whichever files had conflicts
git commit -m "merge: resolve conflicts with main in <files>"
git push

### 5. Confirm GitHub sees it as mergeable

gh pr view <number> --json mergeable,mergeStateStatus

`mergeable: MERGEABLE` means the conflict warning is cleared.

## Key lesson

Working on the wrong branch is the most common source of "no conflicts locally but GitHub still shows conflicts." Always run step 1 before touching any files.

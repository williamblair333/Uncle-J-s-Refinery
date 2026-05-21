---
name: auto-maintain-commit-and-deploy
description: Use when a cron-based auto-maintenance script commits new skills or plugins to git but the install script still has a hardcoded list that needs manual updating, or when new artifacts are committed but not immediately deployed (symlinked, copied, activated). Covers replacing hardcoded artifact lists with dynamic directory scanning and coupling git commits with immediate deployment steps.
metadata:
  type: feedback
---

## When to use

- A nightly cron commits new skill/plugin directories to git but `~/.claude/skills/` (or equivalent) is not updated until the next manual install run
- An install script has a hardcoded list of artifact names that must be maintained by hand
- New artifacts land in a well-known directory but are not immediately live after commit

## Key steps demonstrated

### 1. Replace hardcoded list with dynamic scan

In the install script, replace any `for skill in name1 name2 name3` loop with a glob over the source directory:

for src in "$STACK_ROOT/global-skills"/*/; do
    [ -d "$src" ] || continue
    skill_name=$(basename "$src")
    dst="$CLAUDE_DIR/skills/$skill_name"
    [ -L "$dst" ] || ln -s "$src" "$dst"
done

Any directory added to `global-skills/` is automatically picked up — no list maintenance.

### 2. Couple git commit with immediate deployment

In the auto-maintain script, after the `git commit` that lands new artifacts, run the same symlink loop inline so artifacts are live before the next session:

# after git commit of new skills...
for src in "$STACK_ROOT/global-skills"/*/; do
    [ -d "$src" ] || continue
    dst="$CLAUDE_DIR/skills/$(basename "$src")"
    [ -L "$dst" ] || ln -s "$src" "$dst"
done

No extra Telegram alert needed — the existing end-of-run notification covers it.

### 3. Upgrade evaluation: bash + Claude hybrid

For post-upgrade change detection across multiple packages:
- Bash fetches commit logs (`git log OLD..NEW --oneline`) and scans for breaking-change keywords (`feat!`, `BREAKING`)
- Pass raw commits to `claude -p` for holistic reasoning about what changed and whether CLAUDE.md routing rules need updating
- This is the A+C hybrid: bash does the mechanical fetch, Claude does the judgment

**Why:** keyword-only bash scanning misses semantic breaking changes; Claude invocation adds reasoning without replacing the cheap keyword pre-filter.

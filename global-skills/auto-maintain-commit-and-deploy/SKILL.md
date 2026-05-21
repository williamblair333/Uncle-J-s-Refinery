---
name: auto-maintain-commit-and-deploy
description: Use when a cron-based auto-maintenance script commits new skills or plugins to git but the install script still has a hardcoded list that needs manual updating, or when new artifacts are committed but not immediately deployed (symlinked, copied, activated). Covers replacing hardcoded artifact lists with dynamic directory scanning and coupling git commits with immediate deployment steps.
---

# Auto-Maintain: Commit and Deploy Together

## Overview

When an auto-maintain cron commits new artifacts (skills, plugins, configs), it should also immediately deploy them in the same step. Hardcoded artifact lists in install scripts create a silent maintenance gap — new artifacts get committed but stay dormant until someone manually updates the list.

## When to Use

- `auto-maintain.sh` or similar cron commits new skills/plugins but the install script has a hardcoded name list
- New artifacts appear in git but aren't live until the next manual `install-*.sh` run
- Skill list in install script is a copy-paste artifact from a prior inventory, not a live scan

## The Two-Part Fix

### 1. Replace hardcoded list with directory glob

**Before (install-reliability.sh):**
for skill in prior-art-check judge outcomes orchestrator; do
    ln -sf "$STACK_ROOT/global-skills/$skill" "$CLAUDE_DIR/skills/$skill"
done

**After:**
for src in "$STACK_ROOT/global-skills"/*/; do
    [ -d "$src" ] || continue
    skill_name=$(basename "$src")
    dst="$CLAUDE_DIR/skills/$skill_name"
    [ -L "$dst" ] || ln -sf "$src" "$dst"
done

Any directory under `global-skills/` is automatically picked up — no list to maintain.

### 2. Couple commit with deploy in auto-maintain

After the `git commit` step that lands new artifacts, immediately run the same glob-based symlink loop. New skills are live before the next Claude session starts, not on the next manual install run.

# Part C: commit new skills
git add global-skills/
git commit -m "chore: auto-add new skills"

# Immediately deploy — don't wait for next install-reliability.sh run
for src in "$STACK_ROOT/global-skills"/*/; do
    [ -d "$src" ] || continue
    ln -sf "$src" "$CLAUDE_DIR/skills/$(basename "$src")"
done

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Only fixing the install script but not auto-maintain | Fix both — they run independently |
| Symlinking without checking `[ -d "$src" ]` | Guard against files mixed in the directory |
| Hardcoding the target dir path | Use a variable (`$CLAUDE_DIR`) so it works across machines |
| Forgetting to update the Telegram/notification message | The alert should list newly-symlinked skills, not just committed ones |

## Related

- `install-script-cp-to-symlink` — covers the silent `cp` failure pattern when a symlink already exists at the destination

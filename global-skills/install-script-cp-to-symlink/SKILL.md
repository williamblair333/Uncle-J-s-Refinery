---
name: install-script-cp-to-symlink
description: Use when a bash install script silently skips steps due to `cp` failing on pre-existing symlinks, or when converting copy-based installs to symlink-based for auto-propagation after `git pull`.
metadata:
  type: feedback
---

## When to Use

- An install script using `set -euo pipefail` exits early with no output after certain steps
- Skills, configs, or assets installed via `cp` don't update after `git pull`
- You need to diagnose why a `cp -r "$src/." "$dst/"` command fails silently

## The Problem Pattern

`cp` errors when source and destination resolve to the same path — which happens when `$dst` is already a symlink back into `$src`. With `set -euo pipefail`, the script exits immediately, silently skipping all subsequent steps.

# This fails if $dst is already a symlink to $src:
cp -r "$src/." "$dst/"

## Diagnosis

1. Check if any destination paths are already symlinks:
   ```bash
   ls -la ~/.claude/skills/
   ```
2. Run the script with `bash -x` or check what the first erroring step is.
3. Confirm: `set -euo pipefail` at the top of the script means any cp error halts everything.

## The Fix: Switch to `ln -sfn`

Replace the `cp` block with a three-case symlink handler:

if [ -L "$dst" ] && [ "$(readlink -f "$dst")" = "$(readlink -f "$src")" ]; then
    echo "already linked: $skill"
    continue
fi
rm -rf "$dst"
ln -sfn "$src" "$dst"
echo "installed: $skill"

**Three cases handled:**
1. Already correct symlink → skip (no error)
2. Stale copy or wrong symlink → replace
3. Missing → create

## Bonus: Auto-propagation After `git pull`

Symlinks into the repo mean `git pull` updates the target immediately — no re-running install scripts. This applies to any file type installed by copy: skills, hooks, config templates, etc.

## Caveats

- `rm -rf "$dst"` before `ln -sfn` is safe for directories but irreversible for non-symlink copies — confirm the directory isn't user-modified before replacing.
- Docker services (e.g., Langfuse) are a separate category — they go down on machine restart unless `restart: unless-stopped` is set in the compose file.

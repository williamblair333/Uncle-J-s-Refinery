
---
name: stale-lock-diagnosis
description: Diagnose and clear stale atomic lock directories that cause background scripts (hooks, miners, automation) to silently skip execution, then verify recovery.
---

## When to use

When a background script or hook that uses `mkdir`-based atomic locking has been silently skipping all runs — symptoms include logs full of "skipped" entries, no output since a specific date, or a lock directory whose mtime predates any running process.

## Key steps

### 1. Identify the lock directories

ls -la ~/.claude/  # or wherever the lock dirs live

Look for `*.lock` directories with old mtimes.

### 2. Confirm no live process holds them

# For each lock dir, check if the PID inside (if any) is still running
stat mempalace-mine-convos.lock
# If mtime is hours/days old and no matching PID exists, it's stale

### 3. Remove the stale locks

rmdir mempalace-mine-convos.lock mempalace-mine-project.lock

Use `rmdir` (not `rm -rf`) — it fails safely if something wrote into the dir.

### 4. Trigger a manual catch-up run

# Run the miner/script directly to process everything missed
mempalace mine  # or whatever the background script is

Watch the log to confirm it actually starts (not "skipped").

### 5. Patch the lock check to be stale-aware

The root cause is that `trap` cleanup doesn't fire on SIGKILL. Add a staleness check to the locking script:

LOCK_DIR="myprocess.lock"
LOCK_MAX_AGE_SECONDS=300  # 5 minutes

if [ -d "$LOCK_DIR" ]; then
  lock_age=$(( $(date +%s) - $(stat -c %Y "$LOCK_DIR") ))
  if [ "$lock_age" -gt "$LOCK_MAX_AGE_SECONDS" ]; then
    rmdir "$LOCK_DIR"  # stale — clear and proceed
  else
    echo "skipped: lock held"
    exit 0
  fi
fi

mkdir "$LOCK_DIR"
trap 'rmdir "$LOCK_DIR"' EXIT

## Notes

- `mkdir` is atomic on most filesystems — safe for single-host locking.
- `trap ... EXIT` fires on normal exit and signals, but **not SIGKILL**. Always add a staleness check.
- After clearing locks, check logs to confirm all missed runs are caught up, not just the most recent one.

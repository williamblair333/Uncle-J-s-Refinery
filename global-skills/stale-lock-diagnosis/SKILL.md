
---
name: stale-lock-diagnosis
description: Diagnose and fix stale lock directories blocking background automation scripts (mine, index, sync jobs). Use when hooks are wired but silently not firing, or when a recurring job stopped producing output without any error.

---

## When to use

A background script uses `mkdir` as an atomic lock and a `trap` to release it on exit. If the process is killed (SIGKILL, OOM, power loss), the trap never fires and the lock directory persists indefinitely. Every subsequent invocation sees the lock and silently bails — no errors, no logs, just silence.

Symptoms:
- Hooks are confirmed wired in `settings.json`
- Log file shows no recent entries, or shows only "skipped" entries
- The target output (memweave corpus, index, etc.) has no new data since a specific date

## Diagnostic steps

1. **Check the log** for the last successful run and any "skipped" / "lock exists" messages.
2. **Find lock directories** — typically `*.lock` dirs under the script's working directory or `~/.claude/`:
   ```bash
   find ~/.claude -name "*.lock" -type d
   ```
3. **Confirm staleness** — check mtime and verify no live process holds the lock:
   ```bash
   stat <lock-dir>
   lsof +D <lock-dir>   # should return nothing
   ```
4. **Remove stale locks**:
   ```bash
   rm -rf <lock-dir>
   ```
5. **Run the job manually** to catch up on missed work:
   ```bash
   bash /path/to/mine-script.sh
   ```
6. **Tail the log** to confirm it runs (not skipped).

## Permanent fix — add stale-lock auto-clear to the script

Insert this block immediately after the lock-acquire attempt in each affected script. Replace `30` with your preferred timeout in minutes:

LOCK_DIR="/path/to/job.lock"
LOCK_MAX_AGE_MINUTES=30

if [ -d "$LOCK_DIR" ]; then
  # Auto-clear if older than threshold and no live process holds it
  if find "$LOCK_DIR" -maxdepth 0 -mmin +$LOCK_MAX_AGE_MINUTES | grep -q .; then
    rm -rf "$LOCK_DIR"
  else
    echo "$(date '+%H:%M:%S'): skipped (locked)" >> "$LOG_FILE"
    exit 0
  fi
fi

mkdir "$LOCK_DIR"
trap "rm -rf '$LOCK_DIR'" EXIT

This replaces a hard "bail if locked" with "bail if locked AND fresh; clear if stale."

## Notes

- `trap` cleans up on `EXIT`, `INT`, `TERM` — but not `SIGKILL`. That's the fundamental gap; the auto-clear threshold is the only reliable mitigation.
- Choose a timeout longer than the job's normal runtime but short enough to detect a stuck run. 30 minutes is a reasonable default for a mine/index job.
- After clearing and running manually, verify output in the target system (memweave index file mtime, corpus file count, etc.) to confirm the catchup completed.

---
name: stop-hook-dedup-guard
description: Use when a Claude Code Stop hook sends a Telegram (or other) notification and the same message arrives duplicated at nearly the same timestamp. Symptom is two identical "⏳ Running…" + message pairs appearing within seconds of each other after closing Claude Code.
---

# Stop Hook Dedup Guard

## Overview

When multiple Claude Code sessions are open simultaneously, every one fires the Stop hook on close. If the hook sends a Telegram notification you get N identical messages at the same timestamp. A file-based dedup window — record the last send time, skip if within N seconds — fixes it in one guard block.

## Diagnosis

- Two (or more) identical Telegram messages at nearly the same timestamp
- Messages appear as pairs — same content repeated within 1–5 seconds
- Reproducible when multiple CC windows or projects were open

**Root cause:** Each CC session maintains its own Stop hook registration. When two sessions close around the same time, both trigger the hook independently with no coordination.

## Fix: File-Based Dedup Window

Add this guard at the top of the hook script, before any `notify` / `curl` / `telegram` call:

```bash
DEDUP_FILE="/tmp/$(basename "$0")-last-sent"
DEDUP_WINDOW=15  # seconds

if [ -f "$DEDUP_FILE" ]; then
    last_sent=$(cat "$DEDUP_FILE")
    now=$(date +%s)
    age=$(( now - last_sent ))
    if [ "$age" -lt "$DEDUP_WINDOW" ]; then
        exit 0  # duplicate within window — skip silently
    fi
fi
date +%s > "$DEDUP_FILE"

# ... rest of hook (send notification, etc.) ...
```

The first invocation writes the timestamp and proceeds; any subsequent invocation within the window exits silently.

## Tuning

| Parameter | Default | Notes |
|-----------|---------|-------|
| `DEDUP_WINDOW` | 15s | CC sessions closing "simultaneously" are within 1–2s; 15s gives generous margin |
| `DEDUP_FILE` | `/tmp/<script>-last-sent` | Name per script to avoid cross-script collisions |

`/tmp` is non-persistent across reboots on most systems — that's fine. This is a soft dedup, not a hard lock. A reboot resets it naturally.

## When NOT to Use

- Hook must fire once per session with a **distinct payload** (per-project data, session ID) → a shared timestamp guard will suppress legitimate separate sends. Use a queue or per-session lock file keyed on `$CLAUDE_SESSION_ID` instead.
- Hook runs at fixed intervals, not on-close → use cron-level dedup (lock file + `flock`) instead.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Window too short (1–2s) | Shell startup + hook overhead can exceed 2s; use ≥10s |
| Same temp file path for multiple hooks | Use `$(basename "$0")` or a unique suffix per script |
| Writing timestamp *after* the send | Write first, send second — a crash between them otherwise blocks the next legitimate run permanently |

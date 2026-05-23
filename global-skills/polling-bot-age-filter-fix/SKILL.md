---
name: polling-bot-age-filter-fix
description: Apply a stale-message age gate to a Python Telegram polling bot to prevent a message backlog from exhausting the hourly rate-limit budget. Use after polling-bot-backlog-diagnosis confirms MAX_AGE_SECONDS is missing.
metadata:
  type: project
---

## When to use

After `polling-bot-backlog-diagnosis` confirms the age filter is absent and the rate-limit state file shows all slots consumed within a single cron window. Symptoms: spiraling `⚠️ Message limit reached` + `⏳ Running…` bursts clustered within 30–45 minutes.

## Root cause this fixes

Without an age gate, any backlog (bot downtime, slow cron) causes every run to reprocess all queued messages. Each message burns a rate-limit slot; the full budget is exhausted in one window, triggering the spiral.

## Steps

### 1. Confirm `datetime` is imported

import datetime

Do **not** add `import time` — use `datetime.datetime.now().timestamp()` for consistency with the rest of the script.

### 2. Find the insertion point

Place the age check **after** the auth/signature check and **before** the rate-limit check in the message-processing loop.

### 3. Add the age filter

MAX_AGE_SECONDS = 600  # module-level constant

msg_age = datetime.datetime.now().timestamp() - msg.get("date", 0)
if msg_age > MAX_AGE_SECONDS:
    log(f"Skipped stale message ({int(msg_age)}s old)")
    continue

600 s (10 min) is safe for minute-cadence cron. Tune upward only if cron interval exceeds 5 minutes. The offset still advances on skipped messages — they are never reprocessed.

### 4. Check the rate-limit state file

Inspect `state/telegram-gateway-ratelimit.json`:
- If all slots are consumed but timestamps are older than `RATE_LIMIT_WINDOW_SECS` (typically 3600 s), **no manual reset needed** — `check_rate_limit` prunes stale timestamps automatically on the next run.
- Only manually clear if timestamps are recent (< 1 h old) and immediate recovery is required.

### 5. Register the edit

register_edit(path="scripts/telegram-gateway-poll.sh")

Keeps jcodemunch's BM25/search cache current.

### 6. Verify on next cron run

Confirm:
- No burst of `⏳ Running…` lines
- Stale messages appear as `Skipped stale message (Xs old)` in the log
- Rate-limit slots survive the full window

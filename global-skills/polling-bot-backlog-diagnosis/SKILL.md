---
name: polling-bot-backlog-diagnosis
description: Diagnose and fix message backlog and notification-spam issues in cron-based polling bots — covers per-run deduplication flags and stale-message age filters
---

## When to use

When a cron-based polling bot (Telegram, Slack, etc.) exhibits either of these symptoms:

- **Notification spam**: Multiple identical rate-limit or error notifications per cron run when a queue backs up
- **Backlog starvation**: Old queued messages burn through hourly rate-limit slots before fresh messages are processed

## Root causes and fixes

### Symptom 1 — Multiple notifications per run

**Root cause**: Each message in the batch independently triggers a notification (e.g., "⚠️ Message limit reached"), so N queued messages = N notifications per cron tick.

**Fix**: Add a per-run boolean flag before the message loop. Only send the notification on the first hit; silently skip subsequent ones (still advance offsets so they won't be reprocessed).

rate_limit_notified = False  # reset before the loop

for message in messages:
    if rate_limited:
        if not rate_limit_notified:
            send("⚠️ Message limit reached")
            rate_limit_notified = True
        continue  # skip; offset still advances

# bash equivalent
rate_limit_notified=false

for msg in "${messages[@]}"; do
    if is_rate_limited; then
        if ! $rate_limit_notified; then
            send_notification "⚠️ Message limit reached"
            rate_limit_notified=true
        fi
        continue
    fi
done

### Symptom 2 — Stale backlog eating rate-limit slots

**Root cause**: Messages queued overnight (or during downtime) are reprocessed in bulk on restart, consuming all rate-limit slots before any fresh messages get through. The pattern: 20× "⏳ Running…" over 40 minutes, then rate limit, repeat.

**Fix**: Skip messages older than a threshold (10 minutes is safe for interactive bots). Telegram's `message.date` is a Unix timestamp.

import time

MAX_MESSAGE_AGE_SECONDS = 600  # 10 minutes

for message in messages:
    age = time.time() - message.date
    if age > MAX_MESSAGE_AGE_SECONDS:
        continue  # silently drop stale message; offset advances

MAX_AGE=600
now=$(date +%s)

msg_time=$(echo "$message" | jq '.date')
age=$(( now - msg_time ))
if (( age > MAX_AGE )); then
    continue
fi

**Apply age filter BEFORE the rate-limit check** — stale messages should never even count against the limit.

## Apply both fixes together

| Symptom | Root cause | Fix |
|---|---|---|
| N× "Message limit reached" per cron run | Each queued message sent its own notification | `rate_limit_notified` flag — one notification per run |
| 20× "⏳ Running…" over 40 min then rate limit | Stale backlog from prior session consuming all hourly slots | Age filter — skip messages older than 10 min |

## Bonus: reset a stuck rate-limit state file

If the bot persists rate-limit state to disk and is stuck, clear it directly:

# Find and inspect the state file
cat /path/to/bot/rate_limit_state.json

# Reset by zeroing the counter (keep structure intact)
echo '{"message_count": 0, "window_start": null}' > /path/to/bot/rate_limit_state.json

The next cron tick picks up fresh messages immediately — no restart needed.

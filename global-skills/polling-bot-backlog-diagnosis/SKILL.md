---
name: polling-bot-backlog-diagnosis
description: Diagnose and fix message backlog and notification-spam issues in cron-based polling bots — covers per-run deduplication flags and stale-message age filters
metadata:
  type: feedback

## When to use

When a cron-based polling bot (Telegram, Slack, etc.) shows either of these symptoms:
- Multiple identical notification messages per cron run (e.g., "⚠️ Message limit reached" appearing 4× instead of once)
- A stale backlog consuming the full rate-limit budget on every reset cycle (e.g., 20 "⏳ Running…" messages over 40 min, then rate limit hit, then repeat)

## Root causes and fixes

### Bug 1: Multiple notifications per cron run

**Symptom:** Each queued message triggers its own rate-limit or error notification. N queued messages → N notifications per run.

**Root cause:** The notification flag is checked per-message rather than per-run.

**Fix:** Set a `rate_limit_notified = False` flag before the message loop. Inside the loop, only send the notification on the first hit and flip the flag. All subsequent rate-limited messages in the same run are silently dropped (advance offsets so they don't reprocess).

rate_limit_notified = False
for message in pending_messages:
    if rate_limited:
        if not rate_limit_notified:
            send("⚠️ Message limit reached")
            rate_limit_notified = True
        advance_offset(message)
        continue
    process(message)

### Bug 2: Stale backlog consuming rate-limit budget

**Symptom:** Bot processes messages from hours ago on every cron cycle, burning all hourly slots before reaching fresh messages.

**Root cause:** No message age check — the bot processes everything in the queue regardless of when it was sent.

**Fix:** Add an age filter immediately after the authorized-chat check (before any Claude call). Telegram's `message.date` is a Unix timestamp. Drop anything older than 10 minutes silently.

import time
MAX_AGE_SECONDS = 600  # 10 minutes

msg_age = time.time() - message.date
if msg_age > MAX_AGE_SECONDS:
    advance_offset(message)
    log(f"Skipped stale message ({int(msg_age)}s old)")
    continue

**Order matters:** Age filter first, then rate-limit dedup. Age filter removes backlog cheaply before any API calls occur.

## Verification steps

1. Check the rate-limit state file — confirm slot count is reasonable (not maxed)
2. Grep the polling script for both fixes: `rate_limit_notified` flag and age check
3. Confirm age check appears before the rate-limit block in the loop
4. If rate-limit state is stuck at max, reset it manually so the next cron run can proceed immediately

## Clearing stuck rate-limit state

If the state file shows the limit already consumed, zero it out directly — don't wait for the hourly reset. The state file path is typically in `tg_security` constants or the script header.

---
name: polling-bot-offset-freeze-diagnosis
description: Diagnose and fix a frozen getUpdates offset in a cron-based Telegram (or similar long-poll) bot caused by two pollers consuming the same bot token. Use when a polling bot suddenly floods old messages, the update offset hasn't advanced for days, or more than one scheduled job calls getUpdates against one token.
---

# Polling-Bot Offset-Freeze Diagnosis

## When to use

A long-poll bot (Telegram `getUpdates`, or any single-consumer poll API) suddenly
re-delivers a backlog of old messages, or the stored offset hasn't moved in days.
Root cause is almost always **two consumers sharing one token**: each `getUpdates`
call ACKs only what *it* sees, so neither advances the shared offset past the
other's reads. The backlog never clears and re-floods on every trigger.

Distinct from backlog/age-filter issues (`polling-bot-backlog-diagnosis`,
`polling-bot-age-filter-fix`) — here the offset is *frozen*, not just old. Fixing
the age filter alone will not unstick a frozen offset.

## Diagnostic steps (verify live state before changing anything)

1. **Read prior incident notes first.** Check memweave and any gitignored
   local-only incident forensics before touching code — the freeze may already
   be characterized.

2. **Confirm the offset is actually frozen.** Read the persisted offset file and
   its mtime. A days-old mtime with a live cron means the value isn't advancing:
   ```bash
   stat -c '%y' state/<offset-file>     # last write time
   cat state/<offset-file>              # current offset value
   ```

3. **Confirm the re-skip loop in the log.** A fresh log timestamp showing the
   poller skipping the same stale backlog every interval (not advancing) confirms
   the bot re-reads and re-discards the same updates each run.

4. **Find the competing consumers.** Enumerate every job that calls the poll API
   against the token — crontab plus any service/daemon:
   ```bash
   crontab -l | grep -i <bot-or-poll-name>
   ```
   For the source search, **use jcodemunch** (`search_text` / `search_symbols`),
   not raw `grep` — grep-guard blocks source greps. Two or more pollers on one
   token = confirmed root cause.

## Fix shape

The fix needs **both halves** — code change alone leaves the backlog stuck:

- **Single-consumer enforcement.** Collapse to exactly one poller per token
  (drop the duplicate cron, or gate concurrent runs behind `flock -n`).
- **Deliberate queue drain.** One-time advance of the offset past the stale
  backlog so the dormant flood can't recur on the next trigger.

## Delivery discipline

- **Batch by risk into separate PRs** when the change set spans security surface,
  cron config, and a one-time data drain — don't ship them as one diff.
- **TDD** the code change: write the failing test (single-consumer / offset-advance
  behavior) before the implementation.
- **Run the pre-mortem skill** before editing security-surface files
  (`scripts/`, auth/control logic, third-party integration) — the discipline hook
  requires it, and it catches TOCTOU/cascade/data-integrity regressions in the
  consumer-locking change.
- **Surface what needs a human at the keyboard** (e.g. confirming inbound works
  under the crontab env after merge) rather than claiming end-to-end verification.

# Stack Update Alerts — Design Spec
*Date: 2026-04-22*

## Purpose

Automatically detect when MCP stack tools (jcodemunch, jdatamunch, jdocmunch, mempalace, serena, context7) have new releases, have Claude analyze relevance to this project, and pitch upgrades to the user via Telegram with one-tap approve/skip. User approval triggers Claude to perform the upgrade.

---

## Architecture Overview

Two scheduled jobs (cron on Linux/Mac, Task Scheduler on Windows) — no always-running process:

1. **Send job** — fires daily at user-configured time. Runs freshness check. If behind, invokes `claude -p` to analyze changelogs and send a Telegram pitch with ✅ / ❌ inline buttons. Writes pending state.
2. **Poll job** — fires every 2 minutes. Reads pending state. If a callback arrived and is within the expiry window, invokes `claude -p` to perform the upgrade and sends a confirmation. If the window has expired, cleans up state silently.

Everything is optional — enabled by running `features/stack-alerts/install.sh` (or `.ps1`). The main `install.sh` offers it as a yes/no prompt at the end.

---

## File Layout

```
features/
  stack-alerts/
    install.sh              ← Linux/Mac interactive setup
    install.ps1             ← Windows interactive setup
    README.md               ← what it does, prerequisites, how to uninstall
lib/
  feature-helpers.sh        ← shared: prompt_yes_no, write_env_var, install_cron, remove_cron
  feature-helpers.ps1       ← Windows equivalents
  notify.sh                 ← dispatcher: reads NOTIFY_CHANNEL, delegates to impl
  notify.ps1
  notify-telegram.sh        ← Telegram send/poll implementation
  notify-telegram.ps1
scripts/
  check-stack-freshness.sh  ← already exists
  check-stack-freshness.ps1 ← NEW: Windows port of freshness check
  stack-alerts-send.sh      ← NEW: analyze + pitch
  stack-alerts-send.ps1
  stack-alerts-poll.sh      ← NEW: poll callback + invoke claude to upgrade
  stack-alerts-poll.ps1
state/
  stack-alerts-pending.json ← gitignored runtime state
  stack-alerts.log          ← gitignored, appended to by both jobs
```

---

## Notification Abstraction

Alert scripts never call Telegram APIs directly. They call functions from `lib/notify.sh`:

- `notify_send_pitch "$message" "$keyboard_json"` — sends message with inline buttons, returns message ID
- `notify_poll_reply "$message_id"` — checks for callback query on that message ID, returns `approved` / `rejected` / `pending`
- `notify_send_text "$message"` — sends plain confirmation/error message

`lib/notify.sh` reads `NOTIFY_CHANNEL` (default: `telegram`) and delegates to `lib/notify-telegram.sh`. Adding Discord later = write `lib/notify-discord.sh`, add one case to the dispatcher. Alert scripts unchanged.

---

## Configuration

Written by installer to:
- **Linux/Mac**: `.env` in project root (gitignored)
- **Windows**: user-level environment variables via `[Environment]::SetEnvironmentVariable`

| Key | Description | Example |
|-----|-------------|---------|
| `NOTIFY_CHANNEL` | Notification backend | `telegram` |
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | `7123456789:AAF...` |
| `TELEGRAM_CHAT_ID` | User's personal chat ID | `123456789` |
| `ALERT_SEND_TIME` | Daily send time (24h HH:MM) | `09:00` |
| `ALERT_EXPIRY_MINUTES` | How long buttons stay valid | `60` |

---

## Scheduled Jobs

### Linux/Mac (cron)
```
# Stack alerts — send daily pitch
0 9 * * * cd /opt/proj/Uncle-J-s-Refinery && bash scripts/stack-alerts-send.sh >> state/stack-alerts.log 2>&1

# Stack alerts — poll for user reply every 2 minutes
*/2 * * * * cd /opt/proj/Uncle-J-s-Refinery && bash scripts/stack-alerts-poll.sh >> state/stack-alerts.log 2>&1
```
Send time is substituted from `ALERT_SEND_TIME` during install.

### Windows (Task Scheduler)
Two tasks registered via `Register-ScheduledTask`:
- `UncleJ-StackAlerts-Send` — daily trigger at configured time, runs `stack-alerts-send.ps1`
- `UncleJ-StackAlerts-Poll` — repetition trigger every 2 minutes, runs `stack-alerts-poll.ps1`

---

## Data Flow — Send Job

```
stack-alerts-send.sh
  │
  ├─ Source .env
  ├─ Check if state/stack-alerts-pending.json exists → exit 0 (already pending)
  ├─ Run scripts/check-stack-freshness.sh → capture output
  ├─ If no upgrades → exit 0
  │
  ├─ Invoke: claude -p "
  │     You are analyzing MCP stack updates for the Uncle J's Refinery project.
  │     Changelog: [output from freshness check]
  │     If any update is relevant (new tools, bug fixes that affect us, behavior changes),
  │     respond with JSON: {relevant: true, message: "medium-detail pitch ≤300 chars"}
  │     If nothing is relevant, respond with JSON: {relevant: false}
  │   "
  │
  ├─ If relevant=false → exit 0 (no pitch sent)
  │
  ├─ Call notify_send_pitch with message + ✅ Upgrade / ❌ Skip buttons
  ├─ Write state/stack-alerts-pending.json:
  │     { "message_id": 123, "sent_at": "2026-04-22T09:00:00Z", "packages": ["jcodemunch-mcp", "mempalace"] }
  └─ Exit 0
```

---

## Data Flow — Poll Job

```
stack-alerts-poll.sh
  │
  ├─ Source .env
  ├─ Check if state/stack-alerts-pending.json exists → exit 0 if not
  ├─ Read message_id, sent_at, packages from pending.json
  │
  ├─ Check expiry: (now - sent_at) > ALERT_EXPIRY_MINUTES
  │     → expired: delete pending.json, exit 0
  │
  ├─ Call notify_poll_reply "$message_id"
  │     → pending: exit 0 (check again in 2 min)
  │     → rejected: delete pending.json, exit 0
  │     → approved:
  │           ├─ Delete pending.json
  │           ├─ Invoke: claude -p "
  │           │     Upgrade these packages in the Uncle J's Refinery venv:
  │           │     [packages list]
  │           │     Run: cd /opt/proj/Uncle-J-s-Refinery && uv pip install --upgrade [packages]
  │           │     Then check if any CLAUDE.md changes are needed based on release notes.
  │           │     Report success/failure as a single sentence.
  │           │   "
  │           └─ Call notify_send_text with Claude's report
  └─ Exit 0
```

---

## State File Schema

`state/stack-alerts-pending.json`:
```json
{
  "message_id": 123456,
  "sent_at": "2026-04-22T09:00:00Z",
  "packages": ["jcodemunch-mcp", "mempalace"]
}
```

Absent = no pending alert. Present = awaiting response. Deleted on: expiry, rejection, or successful upgrade.

---

## Installer Flow (`features/stack-alerts/install.sh`)

1. Check dependencies: `curl`, `jq`, `claude` — exit with instructions if missing
2. Prompt: Telegram bot token (required)
3. Prompt: Telegram chat ID (required) — show instructions for finding it
4. Prompt: Daily send time (default: `09:00`)
5. Prompt: Expiry window in minutes (default: `60`)
6. Write all five config keys to `.env`
7. Install cron jobs (idempotent — remove existing Uncle-J stack-alert crons first)
8. Send test Telegram message: "✅ Uncle J's Refinery stack alerts configured."
9. Print summary: what was installed, how to uninstall (`features/stack-alerts/install.sh --uninstall`)

### Windows (`install.ps1`)
Same flow, using:
- `[Environment]::SetEnvironmentVariable` for config
- `Register-ScheduledTask` for scheduling
- `Invoke-WebRequest` for test message

---

## Main install.sh Integration

At the end of the existing `install.sh` opt-in block (after core setup):

```bash
source lib/feature-helpers.sh
if prompt_yes_no "Enable automated stack update alerts via Telegram?"; then
  bash features/stack-alerts/install.sh
fi
```

Same pattern for all future features — one additional `prompt_yes_no` block per feature.

---

## Future Notification Channels

To add Discord:
1. Write `lib/notify-discord.sh` implementing `notify_send_pitch`, `notify_poll_reply`, `notify_send_text`
2. Add `discord)` case to dispatcher in `lib/notify.sh`
3. Add Discord-specific config keys to installer prompts
4. User sets `NOTIFY_CHANNEL=discord` in `.env`

Alert scripts (`stack-alerts-send.sh`, `stack-alerts-poll.sh`) require zero changes.

---

## Error Handling

| Failure | Behavior |
|---------|----------|
| Freshness check fails (network) | Send job exits silently — no pitch, no state written |
| `claude -p` invocation fails | Send job exits, logs error; no pitch sent |
| Telegram API unreachable | `notify_send_pitch` returns error; send job logs and exits cleanly |
| Callback poll returns error | Poll job logs and exits — tries again in 2 min |
| Upgrade fails | Claude reports failure via Telegram; pending state deleted |

---

## Uninstall

`features/stack-alerts/install.sh --uninstall` (and `.ps1 -Uninstall`):
1. Remove the two cron entries / Task Scheduler tasks
2. Delete `state/stack-alerts-pending.json` if present
3. Print instructions for manually removing config keys from `.env` / Windows env vars (does not auto-delete secrets)

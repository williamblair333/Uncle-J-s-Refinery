# Stack Update Alerts

Get a Telegram message when Claude finds an update that matters to your tools. This check covers the MCP stack, the collection of services that give the assistant access to extra tools. Tap ✅ to upgrade or ❌ to skip.

## How It Works

1. The daily job checks for new versions with `scripts/check-stack-freshness.sh`.
2. When a newer version is available, the job uses `claude -p` to read the release notes and decide whether the update matters for your setup.
3. If relevant, sends you a Telegram message with ✅ Upgrade / ❌ Skip buttons.
4. A separate job checks Telegram for your reply every 2 minutes.
5. If you tap ✅, Claude runs `uv pip install --upgrade` and confirms in Telegram.
6. If you tap ❌ or the buttons expire, the job clears the alert without sending a follow-up.

## Prerequisites

- `curl`, `jq`, `python3` on PATH
- `claude` CLI (Claude Code) on PATH
- A Telegram bot token (from [@BotFather](https://t.me/botfather))
- Your Telegram chat ID

**Finding your chat ID:**
1. Send any message to your bot.
2. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Look for `"chat":{"id":XXXXXXXXX}` in the response.

## Install

```bash
bash features/stack-alerts/install.sh
```

`install.sh` also offers this as an opt-in prompt.

## Uninstall

```bash
bash features/stack-alerts/install.sh --uninstall
```

Then remove the five config keys from `.env`.

## Logs

Both jobs write to `state/stack-alerts.log`.

## Config Keys

| Key | Description | Default |
|-----|-------------|---------|
| `NOTIFY_CHANNEL` | Service that delivers alerts | `telegram` |
| `TELEGRAM_BOT_TOKEN` | From @BotFather | required |
| `TELEGRAM_CHAT_ID` | Your personal chat ID | required |
| `ALERT_SEND_TIME` | Time to send the daily alert (HH:MM, 24h clock) | `09:00` |
| `ALERT_EXPIRY_MINUTES` | How long buttons stay valid | `60` |

## Adding a New Notification Channel (e.g. Discord)

1. Create `lib/notify-discord.sh` implementing `_discord_send_pitch`,
   `_discord_poll_reply`, `_discord_send_text` with the same signatures as the
   Telegram equivalents.
2. Add a `discord)` case to `lib/notify.sh`.
3. Set `NOTIFY_CHANNEL=discord` in `.env`.

The alert scripts require no changes.

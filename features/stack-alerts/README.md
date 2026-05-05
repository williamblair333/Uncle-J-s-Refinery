# Stack Update Alerts

Automated daily check for updates to the MCP stack tools, with Claude analysis
and a Telegram pitch when something relevant lands. You tap ✅ or ❌; Claude
does the rest.

## How It Works

1. **Daily send job** checks `scripts/check-stack-freshness.sh` for new versions.
2. If behind, invokes `claude -p` to analyze changelogs for relevance.
3. If relevant, sends you a Telegram message with ✅ Upgrade / ❌ Skip buttons.
4. **Every-2-min poll job** watches for your tap.
5. ✅ → Claude runs `uv pip install --upgrade` and confirms via Telegram.
6. ❌ or no reply within the expiry window → silently cleaned up.

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

`state/stack-alerts.log` — appended to by both the send and poll jobs.

## Config Keys

| Key | Description | Default |
|-----|-------------|---------|
| `NOTIFY_CHANNEL` | Notification backend | `telegram` |
| `TELEGRAM_BOT_TOKEN` | From @BotFather | required |
| `TELEGRAM_CHAT_ID` | Your personal chat ID | required |
| `ALERT_SEND_TIME` | Daily pitch time (HH:MM 24h) | `09:00` |
| `ALERT_EXPIRY_MINUTES` | How long buttons stay valid | `60` |

## Adding a New Notification Channel (e.g. Discord)

1. Create `lib/notify-discord.sh` implementing `_discord_send_pitch`,
   `_discord_poll_reply`, `_discord_send_text` with the same signatures as the
   Telegram equivalents.
2. Add a `discord)` case to `lib/notify.sh`.
3. Set `NOTIFY_CHANNEL=discord` in `.env`.

The alert scripts require no changes.

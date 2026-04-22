#!/usr/bin/env bash
# Interactive setup for stack update alerts (Linux/Mac).
# Usage:
#   bash features/stack-alerts/install.sh            # install
#   bash features/stack-alerts/install.sh --uninstall

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJ_ROOT/.env"

source "$PROJ_ROOT/lib/feature-helpers.sh"

step()  { printf '\n==> %s\n' "$*"; }
ok()    { printf '    OK  %s\n' "$*"; }
warn()  { printf '    !!  %s\n' "$*" >&2; }

CRON_MARKER_SEND="uncle-j-stack-alerts-send"
CRON_MARKER_POLL="uncle-j-stack-alerts-poll"

# ── Uninstall mode ──────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
  step "Uninstalling stack alerts"
  remove_cron "$CRON_MARKER_SEND"
  remove_cron "$CRON_MARKER_POLL"
  rm -f "$PROJ_ROOT/state/stack-alerts-pending.json"
  ok "Cron jobs removed and pending state cleared."
  echo ""
  echo "  To also remove secrets, delete these lines from $ENV_FILE:"
  echo "    NOTIFY_CHANNEL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,"
  echo "    ALERT_SEND_TIME, ALERT_EXPIRY_MINUTES"
  exit 0
fi

# ── Dependency check ─────────────────────────────────────────────────────────
step "Checking dependencies"
for cmd in curl jq python3; do
  if ! command -v "$cmd" &>/dev/null; then
    warn "$cmd not found — install it and re-run."
    exit 1
  fi
  ok "$cmd"
done

CLAUDE_BIN=$(command -v claude 2>/dev/null || true)
if [[ -z "$CLAUDE_BIN" ]]; then
  warn "claude CLI not found on PATH — install Claude Code and re-run."
  exit 1
fi
ok "claude at $CLAUDE_BIN"

# ── Config prompts ────────────────────────────────────────────────────────────
step "Configuration"
echo ""
echo "  You need a Telegram bot token and your chat ID."
echo "  Token: message @BotFather → /mybots → select bot → API Token"
echo "  Chat ID: send any message to your bot, then visit:"
echo "    https://api.telegram.org/bot<TOKEN>/getUpdates"
echo "  and look for \"chat\":{\"id\":XXXXXXX}"
echo ""

prompt_value "Telegram bot token" "" TELEGRAM_BOT_TOKEN
[[ -z "$TELEGRAM_BOT_TOKEN" ]] && { warn "Bot token required."; exit 1; }

prompt_value "Telegram chat ID" "" TELEGRAM_CHAT_ID
[[ -z "$TELEGRAM_CHAT_ID" ]] && { warn "Chat ID required."; exit 1; }

prompt_value "Daily send time (24h HH:MM)" "09:00" ALERT_SEND_TIME
prompt_value "Alert expiry window (minutes)" "60"    ALERT_EXPIRY_MINUTES

# ── Write config ──────────────────────────────────────────────────────────────
step "Writing config to $ENV_FILE"
write_env_var "$ENV_FILE" "NOTIFY_CHANNEL"       "telegram"
write_env_var "$ENV_FILE" "TELEGRAM_BOT_TOKEN"   "$TELEGRAM_BOT_TOKEN"
write_env_var "$ENV_FILE" "TELEGRAM_CHAT_ID"     "$TELEGRAM_CHAT_ID"
write_env_var "$ENV_FILE" "ALERT_SEND_TIME"      "$ALERT_SEND_TIME"
write_env_var "$ENV_FILE" "ALERT_EXPIRY_MINUTES" "$ALERT_EXPIRY_MINUTES"
ok ".env updated"

# ── Install cron jobs ─────────────────────────────────────────────────────────
step "Installing cron jobs"
SEND_HOUR=$(echo "$ALERT_SEND_TIME" | cut -d: -f1 | sed 's/^0//')
SEND_MIN=$(echo "$ALERT_SEND_TIME"  | cut -d: -f2 | sed 's/^0//')
[[ -z "$SEND_HOUR" ]] && SEND_HOUR=0
[[ -z "$SEND_MIN"  ]] && SEND_MIN=0

# PATH must be explicit in cron — its default is /usr/bin:/bin only.
# cd must come before any VAR=val assignment (builtins don't accept env prefix).
CRON_PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
SEND_ENTRY="${SEND_MIN} ${SEND_HOUR} * * * PATH=${CRON_PATH} cd ${PROJ_ROOT} && CLAUDE_BIN=${CLAUDE_BIN} bash scripts/stack-alerts-send.sh >> state/stack-alerts.log 2>&1"
POLL_ENTRY="*/2 * * * * PATH=${CRON_PATH} cd ${PROJ_ROOT} && CLAUDE_BIN=${CLAUDE_BIN} bash scripts/stack-alerts-poll.sh >> state/stack-alerts.log 2>&1"

install_cron "$CRON_MARKER_SEND" "$SEND_ENTRY"
ok "Send cron: ${SEND_MIN} ${SEND_HOUR} * * *"

install_cron "$CRON_MARKER_POLL" "$POLL_ENTRY"
ok "Poll cron: */2 * * * *"

# ── Smoke test ────────────────────────────────────────────────────────────────
step "Sending test Telegram message"
set -a; source "$ENV_FILE"; set +a
source "$PROJ_ROOT/lib/notify.sh"
notify_send_text "✅ Uncle J's Refinery stack alerts configured. You'll receive upgrade pitches at ${ALERT_SEND_TIME} daily."
ok "Test message sent — check your Telegram."

# ── Summary ───────────────────────────────────────────────────────────────────
step "Done"
echo ""
echo "  Two cron jobs installed:"
echo "    • stack-alerts-send  — daily at ${ALERT_SEND_TIME}"
echo "    • stack-alerts-poll  — every 2 minutes"
echo ""
echo "  To uninstall:  bash features/stack-alerts/install.sh --uninstall"
echo "  Logs:          $PROJ_ROOT/state/stack-alerts.log"

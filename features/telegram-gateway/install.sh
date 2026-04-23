#!/usr/bin/env bash
# features/telegram-gateway/install.sh
# Installs (or removes) the Telegram → Claude gateway cron poll job.
# Usage:
#   bash features/telegram-gateway/install.sh            # install
#   bash features/telegram-gateway/install.sh --uninstall

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

source "$PROJ_ROOT/lib/feature-helpers.sh"

step()  { printf '\n==> %s\n' "$*"; }
ok()    { printf '    OK  %s\n' "$*"; }
warn()  { printf '    !!  %s\n' "$*" >&2; }

CRON_MARKER="uncle-j-telegram-gateway"
OFFSET_FILE="$PROJ_ROOT/state/telegram-gateway-offset.txt"

# ── Uninstall mode ────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
  step "Uninstalling telegram-gateway"
  remove_cron "$CRON_MARKER"
  rm -f "$OFFSET_FILE"
  ok "Cron job removed and offset state cleared."
  exit 0
fi

# ── Dependency check ──────────────────────────────────────────────────────────
step "Checking dependencies"
for cmd in curl python3 jq; do
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

# ── Load .env — fall back to main worktree if this worktree has none ──────────
step "Loading .env"
ENV_FILE="$PROJ_ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  GIT_COMMON="$(git -C "$PROJ_ROOT" rev-parse --git-common-dir 2>/dev/null || true)"
  if [[ -n "$GIT_COMMON" ]]; then
    MAIN_ROOT="$(cd "$GIT_COMMON/.." && pwd)"
    [[ -f "$MAIN_ROOT/.env" ]] && ENV_FILE="$MAIN_ROOT/.env"
  fi
fi
if [[ ! -f "$ENV_FILE" ]]; then
  warn ".env not found (checked $PROJ_ROOT/.env and main worktree)."
  warn "Run features/stack-alerts/install.sh first to configure TELEGRAM_BOT_TOKEN."
  exit 1
fi
set -a
# shellcheck source=../../.env
source "$ENV_FILE"
set +a
ok "Loaded $ENV_FILE"

# ── Verify TELEGRAM_BOT_TOKEN is present ─────────────────────────────────────
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  warn "TELEGRAM_BOT_TOKEN is not set in $ENV_FILE."
  warn "Run features/stack-alerts/install.sh to configure it."
  exit 1
fi
ok "TELEGRAM_BOT_TOKEN present"

if [[ -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  warn "TELEGRAM_CHAT_ID is not set in $ENV_FILE."
  warn "Run features/stack-alerts/install.sh to configure it."
  exit 1
fi
ok "TELEGRAM_CHAT_ID present"

# ── Validate bot token via getMe ──────────────────────────────────────────────
step "Validating bot token via Telegram getMe"
GETME_RESP=$(curl -sf "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" 2>/dev/null || echo '{"ok":false}')
if ! echo "$GETME_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)" 2>/dev/null; then
  warn "Telegram getMe failed — check TELEGRAM_BOT_TOKEN in $ENV_FILE."
  warn "Response: $GETME_RESP"
  exit 1
fi
BOT_NAME=$(echo "$GETME_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('result',{}).get('username','?'))" 2>/dev/null || echo "?")
ok "Bot validated: @${BOT_NAME}"

# ── Install cron job ──────────────────────────────────────────────────────────
step "Installing cron job"

POLL_SCRIPT="$PROJ_ROOT/scripts/telegram-gateway-poll.sh"
if [[ ! -f "$POLL_SCRIPT" ]]; then
  warn "Poll script not found at $POLL_SCRIPT"
  warn "Run Task B1 first to create scripts/telegram-gateway-poll.sh."
  exit 1
fi

CRON_PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
LOG_FILE="$PROJ_ROOT/state/telegram-gateway.log"
CRON_ENTRY="*/2 * * * * PATH=${CRON_PATH} CLAUDE_BIN=${CLAUDE_BIN} bash ${POLL_SCRIPT} >> ${LOG_FILE} 2>&1"

install_cron "$CRON_MARKER" "$CRON_ENTRY"
ok "Cron installed: */2 * * * *"

# ── Send Telegram confirmation ────────────────────────────────────────────────
step "Sending Telegram confirmation"
source "$PROJ_ROOT/lib/notify.sh"
notify_send_text "✅ Uncle J's Telegram gateway is <b>active</b>. Messages from chat ID <code>${TELEGRAM_CHAT_ID}</code> will be forwarded to Claude every 2 minutes."
ok "Confirmation sent to chat ID ${TELEGRAM_CHAT_ID}"

# ── Summary ───────────────────────────────────────────────────────────────────
step "Done"
echo ""
echo "  Cron job installed: uncle-j-telegram-gateway (*/2 * * * *)"
echo ""
echo "  Send any message to @${BOT_NAME} from chat ${TELEGRAM_CHAT_ID}."
echo "  Claude will reply within ~2 minutes."
echo ""
echo "  Logs:       $LOG_FILE"
echo "  Uninstall:  bash $SCRIPT_DIR/install.sh --uninstall"
echo ""

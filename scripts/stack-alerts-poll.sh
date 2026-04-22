#!/usr/bin/env bash
# Every-2-min poll job: check for user's Telegram reply, upgrade if approved.
# Cron runs this; stdout/stderr go to state/stack-alerts.log.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_FILE="$PROJ_ROOT/state/stack-alerts-pending.json"
LOG_FILE="$PROJ_ROOT/state/stack-alerts.log"
ENV_FILE="$PROJ_ROOT/.env"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "claude")}"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"; }

# No pending state — nothing to do
[[ -f "$STATE_FILE" ]] || exit 0

# Load config
[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

source "$PROJ_ROOT/lib/notify.sh"

# Read state
message_id=$(python3 -c "import sys,json; print(json.load(open(sys.argv[1]))['message_id'])" "$STATE_FILE")
sent_at=$(python3 -c "import sys,json; print(json.load(open(sys.argv[1]))['sent_at'])" "$STATE_FILE")
packages=$(python3 -c "import sys,json; print(json.dumps(json.load(open(sys.argv[1]))['packages']))" "$STATE_FILE")

# Check expiry
expired=$(python3 - "$sent_at" "${ALERT_EXPIRY_MINUTES:-60}" << 'PYEOF'
import sys, datetime
sent_at_str, expiry_min = sys.argv[1], int(sys.argv[2])
sent_at = datetime.datetime.strptime(sent_at_str, "%Y-%m-%dT%H:%M:%SZ")
elapsed = (datetime.datetime.utcnow() - sent_at).total_seconds() / 60
print("true" if elapsed > expiry_min else "false")
PYEOF
)

if [[ "$expired" == "true" ]]; then
  log "Alert window expired (>${ALERT_EXPIRY_MINUTES:-60} min). Cleaning up state."
  rm -f "$STATE_FILE"
  exit 0
fi

reply=$(notify_poll_reply "$message_id")

case "$reply" in
  pending)
    exit 0
    ;;
  rejected)
    log "User skipped upgrade. Cleaning up state."
    rm -f "$STATE_FILE"
    notify_send_text "⏭ Upgrade skipped. Will check again tomorrow." || true
    exit 0
    ;;
  approved)
    log "User approved upgrade. Invoking Claude to upgrade packages..."
    rm -f "$STATE_FILE"

    pkg_list=$(echo "$packages" | python3 -c \
      "import sys,json; print(' '.join(json.loads(sys.stdin.read())))")

    upgrade_prompt="Upgrade these Python packages in the Uncle J's Refinery venv.
Run exactly: cd $PROJ_ROOT && uv pip install --upgrade $pkg_list
Then check if the release notes for these packages require any changes to CLAUDE.md.
Respond with one sentence: what was upgraded and whether CLAUDE.md needed changes."

    if ! result=$("$CLAUDE_BIN" --allowed-tools 'Bash' -p "$upgrade_prompt" 2>/dev/null); then
      result="Upgrade command failed — check logs and run manually: uv pip install --upgrade $pkg_list"
    fi

    log "Upgrade result: $result"
    notify_send_text "🔧 $result" || true
    ;;
esac

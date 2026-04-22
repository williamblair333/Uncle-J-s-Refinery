#!/usr/bin/env bash
# Daily send job: check for stack updates, analyze with Claude, pitch via Telegram.
# Cron runs this; stdout/stderr go to state/stack-alerts.log.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_FILE="$PROJ_ROOT/state/stack-alerts-pending.json"
LOG_FILE="$PROJ_ROOT/state/stack-alerts.log"
ENV_FILE="$PROJ_ROOT/.env"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "claude")}"

mkdir -p "$PROJ_ROOT/state"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"; }

# Load config
[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

# Source notify abstraction
source "$PROJ_ROOT/lib/notify.sh"

# Idempotency guard — don't send if a pitch is already pending
if [[ -f "$STATE_FILE" ]]; then
  log "Pending state exists — skipping send (user hasn't responded yet)."
  exit 0
fi

log "Running freshness check..."
freshness_output=$(bash "$SCRIPT_DIR/check-stack-freshness.sh" 2>&1) && freshness_exit=0 || freshness_exit=$?

if [[ $freshness_exit -eq 0 ]]; then
  log "All packages current. Nothing to pitch."
  exit 0
fi

log "Updates detected. Invoking Claude for relevance analysis..."

prompt="You are analyzing MCP stack updates for the Uncle J's Refinery project.
This project is a Claude Code harness that relies on jcodemunch, jdatamunch, jdocmunch,
mempalace, serena, and context7 as core retrieval and memory tools.

Freshness check output:
${freshness_output}

If any update contains something meaningful to this project (new tools, behavior changes,
bug fixes that could affect us, breaking changes), respond with ONLY this JSON — no other text:
{\"relevant\":true,\"message\":\"<pitch ≤280 chars: name the packages and explain the impact>\",\"packages\":[\"pkg-name\"]}

If nothing is meaningfully relevant (trivial internals, unrelated platforms, cosmetic), respond ONLY:
{\"relevant\":false}"

analysis=$("$CLAUDE_BIN" -p "$prompt" 2>/dev/null) || {
  log "ERROR: claude -p invocation failed. No pitch sent."
  exit 0
}

relevant=$(printf '%s\n' "$analysis" | python3 -c \
  "import sys,json; d=json.loads(sys.stdin.read()); print(str(d.get('relevant',False)).lower())" \
  2>/dev/null || echo "false")

if [[ "$relevant" != "true" ]]; then
  log "Claude: updates not relevant to this project. No pitch sent."
  exit 0
fi

message=$(printf '%s\n' "$analysis" | python3 -c \
  "import sys,json; print(json.loads(sys.stdin.read())['message'])" 2>/dev/null)
packages=$(echo "$analysis" | python3 -c \
  "import sys,json; print(json.dumps(json.loads(sys.stdin.read())['packages']))" 2>/dev/null)

if [[ -z "$message" || -z "$packages" ]]; then
  log "ERROR: Claude response missing 'message' or 'packages'. No pitch sent."
  exit 0
fi

keyboard='[[{"text":"✅ Upgrade","callback_data":"approve"},{"text":"❌ Skip","callback_data":"skip"}]]'

log "Sending Telegram pitch..."
message_id=$(notify_send_pitch "$message" "$keyboard") || {
  log "ERROR: Telegram send failed. No state written."
  exit 0
}

# Write pending state
python3 - "$message_id" "$packages" << 'PYEOF' > "$STATE_FILE"
import sys, json, datetime
state = {
    "message_id": int(sys.argv[1]),
    "sent_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "packages": json.loads(sys.argv[2])
}
print(json.dumps(state, indent=2))
PYEOF

log "Pitch sent (message_id=${message_id}). Waiting for user response."

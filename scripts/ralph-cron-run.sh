#!/usr/bin/env bash
# Cron-safe wrapper: runs ralph-harness.sh with env-var config, logs to
# state/ralph-cron.log, and sends Telegram notifications on start/finish.
#
# Usage (cron):
#   RALPH_PRD=/path/to/PRD.md RALPH_MAX_ITER=10 bash /path/to/scripts/ralph-cron-run.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJ_ROOT/state/ralph-cron.log"
ENV_FILE="$PROJ_ROOT/.env"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"; }

# Load .env if present
[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

# Source notify.sh (soft — skip if missing)
[[ -f "$PROJ_ROOT/lib/notify.sh" ]] && source "$PROJ_ROOT/lib/notify.sh"

# Determine whether Telegram is available
_tg_ok() {
  [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]
}

_notify() {
  local msg=$1
  if _tg_ok && declare -f notify_send_text &>/dev/null; then
    notify_send_text "$msg" || true
  fi
}

# Validate RALPH_PRD
if [[ -z "${RALPH_PRD:-}" ]]; then
  log "ERROR: RALPH_PRD is not set — aborting."
  exit 1
fi
if [[ ! -f "$RALPH_PRD" ]]; then
  log "ERROR: RALPH_PRD file not found: $RALPH_PRD — aborting."
  exit 1
fi

# Validate ralph-harness.sh exists
HARNESS="$PROJ_ROOT/ralph-harness.sh"
if [[ ! -f "$HARNESS" ]]; then
  log "ERROR: ralph-harness.sh not found at $HARNESS — aborting."
  exit 1
fi

# Resolve config with defaults
RALPH_REPO="${RALPH_REPO:-$PROJ_ROOT}"
RALPH_MAX_ITER="${RALPH_MAX_ITER:-10}"
RALPH_RISK_THRESHOLD="${RALPH_RISK_THRESHOLD:-0.65}"

PRD_BASE="$(basename "$RALPH_PRD")"

# Build command array
CMD=(
  bash "$HARNESS"
  --prd "$RALPH_PRD"
  --repo "$RALPH_REPO"
  --max-iterations "$RALPH_MAX_ITER"
  --risk-threshold "$RALPH_RISK_THRESHOLD"
)
[[ "${RALPH_SKIP_JUDGE:-}"  == "1"  ]] && CMD+=(--skip-judge)
[[ "${RALPH_DRY_RUN:-}"    == "1"  ]] && CMD+=(--dry-run)
[[ -n "${RALPH_PRE_SCRIPT:-}"      ]] && CMD+=(--pre-script "$RALPH_PRE_SCRIPT")

# Log + notify: run starting
log "Starting ralph run: prd=$RALPH_PRD repo=$RALPH_REPO max-iter=$RALPH_MAX_ITER risk=$RALPH_RISK_THRESHOLD"
_notify "🔁 Ralph run starting for <code>${PRD_BASE}</code> (max ${RALPH_MAX_ITER} iter)"

START_TS=$(date +%s)

# Run harness — capture exit code without aborting the wrapper
set +e
"${CMD[@]}"
rc=$?
set -e

END_TS=$(date +%s)
elapsed=$(( END_TS - START_TS ))

log "ralph-harness.sh finished: exit=${rc} elapsed=${elapsed}s"

# Send outcome notification
case "$rc" in
  0)
    _notify "✅ Ralph run <b>DONE</b> for <code>${PRD_BASE}</code> after ${elapsed}s"
    ;;
  2)
    _notify "⚠️ Ralph run hit max iterations for <code>${PRD_BASE}</code> — inspect PRD and repo diff"
    ;;
  *)
    _notify "❌ Ralph run <b>FAILED</b> (exit ${rc}) for <code>${PRD_BASE}</code>"
    ;;
esac

exit "$rc"

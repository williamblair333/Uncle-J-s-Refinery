#!/usr/bin/env bash
# Daily cron: run healthcheck and notify Will via Telegram on failures.
# Exits 0 always — cron must not fail loudly on transient issues.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJ_ROOT/.env"
LOG="$PROJ_ROOT/state/healthcheck-notify.log"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

mkdir -p "$PROJ_ROOT/state"
[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
    log "Missing Telegram credentials — skipping."
    exit 0
fi

source "$PROJ_ROOT/lib/notify.sh"

log "Running healthcheck..."
# Capture stdout+stderr merged; healthcheck exits 1 on failure
FULL_OUTPUT=$(bash "$PROJ_ROOT/healthcheck.sh" 2>&1) && HC_EXIT=0 || HC_EXIT=$?

if [[ "$HC_EXIT" -eq 0 ]]; then
    log "Healthcheck passed — no notification sent."
    exit 0
fi

# Extract failure detail lines (written by bad() as "    X   <reason>")
FAILURES=$(printf '%s\n' "$FULL_OUTPUT" | grep -E '^\s+X\s+' | sed 's/^\s*X\s*//' | head -8 || true)
# Extract machine summary from final HEALTHCHECK line
SUMMARY=$(printf '%s\n' "$FULL_OUTPUT" | grep '^HEALTHCHECK:' | tail -1 || true)
FAIL_COUNT=$(printf '%s\n' "$SUMMARY" | grep -oP '(?<=fail \()\d+' || echo "?")

MSG="🔴 <b>Health check failed</b> (${FAIL_COUNT} issue(s))"
if [[ -n "$FAILURES" ]]; then
    MSG="${MSG}
$(printf '%s\n' "$FAILURES" | sed 's/^/• /')"
fi
MSG="${MSG}

Run <code>/health</code> for details."

log "Sending failure notification (${FAIL_COUNT} issue(s))"
# Log WHICH checks failed, not just how many. Until now the only copy of that
# detail was the Telegram message, so this log recorded twenty consecutive
# failures (2026-08-03 → 2026-08-28) that could not be told apart or triaged
# after the fact. $FAILURES holds bad() lines only; the credentials check sends
# its matched lines to stderr without an X prefix, so no secret reaches here.
if [[ -n "$FAILURES" ]]; then
    while IFS= read -r line; do
        [[ -n "$line" ]] && log "  X $line"
    done <<< "$FAILURES"
fi
notify_send_text "$MSG" || log "ERROR: Failed to send Telegram notification"

#!/usr/bin/env bash
# session-end-check.sh — Session-end documentation gate.
#
# Usage:
#   ./session-end-check.sh              # pre-commit mode (default — blocks on missing docs)
#   ./session-end-check.sh --stop-hook  # Stop hook mode (warns via Telegram, never blocks)
#
# Reads .session-end.yml from the git root. Exits 0 (pass) when:
#   - No .session-end.yml found (repo opted out)
#   - No staged/modified files match trigger.file_types
#   - All mandatory docs are staged (pre-commit) or modified since HEAD (stop-hook)
#
# Exits 1 (block) in pre-commit mode when mandatory docs are missing from the staged diff.

set -euo pipefail

MODE="${1:-}"
PROJ_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
CONFIG_FILE="$PROJ_ROOT/.session-end.yml"

[[ -f "$CONFIG_FILE" ]] || exit 0

# Prefer venv python (has pyyaml); fall back to system python3
PYTHON="$PROJ_ROOT/.venv/bin/python3"
[[ -x "$PYTHON" ]] || PYTHON="python3"

# ── Collect changed files ────────────────────────────────────────────────────
if [[ "$MODE" == "--stop-hook" ]]; then
    CHANGED_FILES=$(git -C "$PROJ_ROOT" diff HEAD --name-only 2>/dev/null || true)
else
    CHANGED_FILES=$(git -C "$PROJ_ROOT" diff --staged --name-only 2>/dev/null || true)
fi

[[ -n "$CHANGED_FILES" ]] || exit 0

# ── Single Python pass: gate check + mandatory check ────────────────────────
# Passes data via env vars (same pattern as telegram-gateway-poll.sh) to avoid
# shell-quoting issues with newlines and special characters.
export SESSION_END_CONFIG="$CONFIG_FILE"
export SESSION_END_CHANGED="$CHANGED_FILES"

RESULT=$("$PYTHON" - <<'PY'
import yaml, os, sys

config    = yaml.safe_load(open(os.environ["SESSION_END_CONFIG"]))
changed   = set(f.strip() for f in os.environ["SESSION_END_CHANGED"].splitlines() if f.strip())

# File-type gate
trigger_exts = set(config.get("trigger", {}).get("file_types", []))
triggered = any(
    os.path.splitext(f)[1] in trigger_exts
    for f in changed
)

if not triggered:
    print("NOT_TRIGGERED")
    sys.exit(0)

# Mandatory doc check
missing = [doc for doc in config.get("mandatory", []) if doc not in changed]
if not missing:
    print("OK")
else:
    print("MISSING:" + ",".join(missing))
PY
)

[[ "$RESULT" == "NOT_TRIGGERED" || "$RESULT" == "OK" ]] && exit 0

# ── Missing mandatory docs — act based on mode ───────────────────────────────
MISSING_LIST="${RESULT#MISSING:}"  # strip "MISSING:" prefix

if [[ "$MODE" == "--stop-hook" ]]; then
    # Stop hook: send Telegram warning (non-blocking — hook must exit 0)
    ENV_FILE="$PROJ_ROOT/.env"
    # shellcheck disable=SC1090
    [[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a 2>/dev/null || true

    if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
        MSG="⚠️ Session ended with stale mandatory docs: ${MISSING_LIST/,/ • } — run session-end-checklist before next commit."
        # Dedup: skip if an identical message was sent in the last 15 s (concurrent sessions)
        DEDUP_FILE="$PROJ_ROOT/state/session-end-dedup.txt"
        MSG_HASH="$(printf '%s' "$MSG" | md5sum | cut -c1-16)"
        NOW="$(date +%s)"
        _skip=0
        if [[ -f "$DEDUP_FILE" ]]; then
            _prev_hash="$(cut -f1 "$DEDUP_FILE" 2>/dev/null)"
            _prev_ts="$(cut -f2   "$DEDUP_FILE" 2>/dev/null)"
            [[ "$_prev_hash" == "$MSG_HASH" && $(( NOW - _prev_ts )) -lt 15 ]] && _skip=1
        fi
        if [[ "$_skip" -eq 0 ]]; then
            printf '%s\t%s\n' "$MSG_HASH" "$NOW" > "$DEDUP_FILE"
            curl -sf -X POST \
                "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
                -H "Content-Type: application/json" \
                -d "{\"chat_id\":\"${TELEGRAM_CHAT_ID}\",\"text\":\"$MSG\"}" \
                >/dev/null 2>&1 || true
        fi
    fi
    exit 0

else
    # Pre-commit: block with actionable error
    echo ""
    echo "❌ Session-end checklist: mandatory docs not staged"
    echo ""
    echo "  Missing:"
    IFS=',' read -ra DOCS <<< "$MISSING_LIST"
    for doc in "${DOCS[@]}"; do
        echo "    • $doc"
    done
    echo ""
    echo "  Run the session-end-checklist skill, or update manually and re-stage."
    echo "  To skip: git commit --no-verify  (use sparingly)"
    echo ""
    exit 1
fi

#!/usr/bin/env bash
# scripts/session-notify.sh — Claude Code Stop hook
# Sends a Telegram summary when a Claude Code session ends.
# Invoked by Claude Code with a JSON payload on stdin.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env
if [[ -f "$REPO_ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "$REPO_ROOT/.env"
  set +a
fi

# Exit cleanly if Telegram credentials are missing
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]] || [[ -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  exit 0
fi

# Source the notification dispatcher
# shellcheck source=lib/notify.sh
[[ -f "$REPO_ROOT/lib/notify.sh" ]] || exit 0
source "$REPO_ROOT/lib/notify.sh"

# Read stdin once
PAYLOAD=$(cat)

# Extract session_id and transcript_path from JSON payload
_py_out="$(printf '%s' "$PAYLOAD" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    sid = data.get('session_id', '')
    tp  = data.get('transcript_path', '')
    print(sid + '\t' + tp)
except Exception:
    print('\t')
")"
SESSION_ID="$(cut -f1 <<< "$_py_out")"
TRANSCRIPT_PATH="$(cut -f2 <<< "$_py_out")"

SHORT_ID="${SESSION_ID:0:8}"
[[ -z "$SHORT_ID" ]] && SHORT_ID="unknown"

# Extract last assistant message text from transcript JSONL
LAST_TEXT=""
if [[ -n "$TRANSCRIPT_PATH" ]] && [[ -f "$TRANSCRIPT_PATH" ]]; then
  LAST_TEXT="$(python3 -c "
import sys, json

path = sys.argv[1]
last_text = ''

try:
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if obj.get('role') != 'assistant':
                continue
            content = obj.get('content', '')
            if isinstance(content, str):
                last_text = content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        last_text = block.get('text', '')
except Exception:
    pass

print(last_text, end='')
" "$TRANSCRIPT_PATH")"
fi

# Build summary (truncate to 800 chars with ellipsis)
MAX=800
if [[ -n "$LAST_TEXT" ]]; then
  BODY="$(printf '🤖 Session <code>%s</code> ended.\n\n%s' "$SHORT_ID" "$LAST_TEXT")"
else
  BODY="$(printf '🤖 Session <code>%s</code> ended.' "$SHORT_ID")"
fi

if (( ${#BODY} > MAX )); then
  SUMMARY="${BODY:0:$MAX}…"
else
  SUMMARY="$BODY"
fi

notify_send_text "$SUMMARY"

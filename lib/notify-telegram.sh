#!/usr/bin/env bash
# Telegram notification backend. Sourced by lib/notify.sh — do not execute directly.
# Requires: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID in environment.

_TG_API="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"
_TG_PY=$(command -v python3)

# Send a message with inline keyboard buttons.
# Args: $1=message text, $2=keyboard JSON array (e.g. '[[{"text":"✅ Yes","callback_data":"approve"}]]')
# Stdout: message_id of the sent message
_tg_send_pitch() {
  local message=$1 keyboard_json=$2
  local tmppy tmppayload
  tmppy=$(mktemp /tmp/tg_pitch_XXXXXX.py)
  tmppayload=$(mktemp /tmp/tg_payload_XXXXXX.json)

  cat > "$tmppy" << 'PYEOF'
import json, sys
chat_id, message, keyboard_str, out_file = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
payload = {
    "chat_id": chat_id,
    "text": message,
    "parse_mode": "HTML",
    "reply_markup": {"inline_keyboard": json.loads(keyboard_str)}
}
with open(out_file, "w") as f:
    json.dump(payload, f)
PYEOF

  "$_TG_PY" "$tmppy" "$TELEGRAM_CHAT_ID" "$message" "$keyboard_json" "$tmppayload" \
    || { rm -f "$tmppy" "$tmppayload"; return 1; }
  rm -f "$tmppy"

  local tmpresponse
  tmpresponse=$(mktemp /tmp/tg_response_XXXXXX.json)
  curl -sf -X POST "${_TG_API}/sendMessage" \
    -H "Content-Type: application/json" \
    -d "@${tmppayload}" > "$tmpresponse" 2>/dev/null
  rm -f "$tmppayload"

  local msg_id
  msg_id=$("$_TG_PY" -c "import sys,json; print(json.load(open(sys.argv[1]))['result']['message_id'])" "$tmpresponse") \
    || { rm -f "$tmpresponse"; return 1; }
  rm -f "$tmpresponse"
  echo "$msg_id"
}

# Poll for a callback query on a specific message.
# Args: $1=message_id
# Stdout: "approved" | "rejected" | "pending"
#
# Single-consumer model (incident F1/F2/F3): the Telegram gateway is the ONLY
# getUpdates consumer. It drains callback_query updates and records approve/skip
# decisions to state/stack-alerts-callback.json; this function only READS that file.
# A second no-offset getUpdates consumer here corrupted the shared update offset and
# caused a 22-day message-flood. The gateway also answers the callback (spinner).
_tg_poll_reply() {
  local message_id=$1
  local proj_root state_file result
  proj_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  state_file="$proj_root/state/stack-alerts-callback.json"

  if ! result=$("$_TG_PY" - "$message_id" "$state_file" "$proj_root" <<'PYEOF'
import sys, os
message_id, state_file, proj_root = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, os.path.join(proj_root, 'scripts', 'lib'))
from tg_security import read_stack_callback
print(read_stack_callback(state_file, int(message_id)))
PYEOF
  ); then
    echo "pending"
    return 0
  fi
  echo "$result"
}

# Send a plain text message (confirmations, errors).
# Args: $1=message text
_tg_send_text() {
  local message=$1 tmppy tmppayload
  tmppy=$(mktemp /tmp/tg_text_XXXXXX.py)
  tmppayload=$(mktemp /tmp/tg_textpayload_XXXXXX.json)

  cat > "$tmppy" << 'PYEOF'
import json, sys
with open(sys.argv[2], "w") as f:
    json.dump({"chat_id": sys.argv[1], "text": sys.argv[3], "parse_mode": "HTML"}, f)
PYEOF

  "$_TG_PY" "$tmppy" "$TELEGRAM_CHAT_ID" "$tmppayload" "$message" \
    || { rm -f "$tmppy" "$tmppayload"; return 1; }
  rm -f "$tmppy"

  curl -sf -X POST "${_TG_API}/sendMessage" \
    -H "Content-Type: application/json" \
    -d "@${tmppayload}" > /dev/null 2>&1 || true
  rm -f "$tmppayload"
}

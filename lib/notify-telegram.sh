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
  local tmppy tmppayload response
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

  "$_TG_PY" "$tmppy" "$TELEGRAM_CHAT_ID" "$message" "$keyboard_json" "$tmppayload"
  rm -f "$tmppy"

  response=$(curl -sf -X POST "${_TG_API}/sendMessage" \
    -H "Content-Type: application/json" \
    -d "@${tmppayload}" 2>/dev/null)
  rm -f "$tmppayload"

  echo "$response" | "$_TG_PY" -c "import sys,json; print(json.load(sys.stdin)['result']['message_id'])"
}

# Poll for a callback query on a specific message.
# Args: $1=message_id
# Stdout: "approved" | "rejected" | "pending"
# Side-effect: calls answerCallbackQuery to dismiss loading indicator if found.
_tg_poll_reply() {
  local message_id=$1
  local tmpjson tmppy result callback_query_id

  tmpjson=$(mktemp /tmp/tg_updates_XXXXXX.json)
  tmppy=$(mktemp /tmp/tg_poll_XXXXXX.py)

  curl -sf "${_TG_API}/getUpdates?allowed_updates=callback_query&limit=100" \
    > "$tmpjson" 2>/dev/null || echo '{"result":[]}' > "$tmpjson"

  cat > "$tmppy" << 'PYEOF'
import sys, json
target_msg_id = int(sys.argv[1])
with open(sys.argv[2]) as f:
    updates = json.load(f)
for update in updates.get("result", []):
    cq = update.get("callback_query", {})
    if not cq:
        continue
    if cq.get("message", {}).get("message_id") == target_msg_id:
        print(cq.get("data", "skip"))   # "approve" or "skip"
        print(cq.get("id", ""))         # callback_query_id on second line
        sys.exit(0)
print("pending")
print("")
PYEOF

  result=$("$_TG_PY" "$tmppy" "$message_id" "$tmpjson")
  rm -f "$tmpjson" "$tmppy"

  local data callback_id
  data=$(echo "$result" | sed -n '1p')
  callback_id=$(echo "$result" | sed -n '2p')

  # Acknowledge callback to dismiss Telegram's loading indicator
  if [[ -n "$callback_id" && "$data" != "pending" ]]; then
    curl -sf -X POST "${_TG_API}/answerCallbackQuery" \
      -H "Content-Type: application/json" \
      -d "{\"callback_query_id\":\"${callback_id}\"}" > /dev/null 2>&1 || true
  fi

  if [[ "$data" == "approve" ]]; then
    echo "approved"
  elif [[ "$data" == "pending" ]]; then
    echo "pending"
  else
    echo "rejected"
  fi
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

  "$_TG_PY" "$tmppy" "$TELEGRAM_CHAT_ID" "$tmppayload" "$message"
  rm -f "$tmppy"

  curl -sf -X POST "${_TG_API}/sendMessage" \
    -H "Content-Type: application/json" \
    -d "@${tmppayload}" > /dev/null 2>&1 || true
  rm -f "$tmppayload"
}

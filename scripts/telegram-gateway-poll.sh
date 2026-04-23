#!/usr/bin/env bash
# Cron job (every 2 min): poll Telegram for messages, run claude --print, reply.
# Cron runs this; stdout/stderr appended to state/telegram-gateway.log.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OFFSET_FILE="$PROJ_ROOT/state/telegram-gateway-offset.txt"
LOG_FILE="$PROJ_ROOT/state/telegram-gateway.log"
ENV_FILE="$PROJ_ROOT/.env"

# Resolve claude binary: env override → PATH
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "claude")}"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"; }

# Load .env if present
[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

# Exit cleanly if credentials are missing
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  log "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID — skipping."
  exit 0
fi

# Read current offset (default 0)
OFFSET="0"
[[ -f "$OFFSET_FILE" ]] && OFFSET="$(cat "$OFFSET_FILE")"
OFFSET="${OFFSET:-0}"

log "Polling Telegram (offset=${OFFSET})"

# Fetch updates via curl (safe: no message content interpolated here)
UPDATES_JSON=$(curl -sf \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates?offset=${OFFSET}&limit=10&allowed_updates=message&timeout=0" \
  2>/dev/null) || UPDATES_JSON='{"ok":false,"result":[]}'

# Hand off all processing to Python to safely handle arbitrary message text
NEW_OFFSET=$(python3 - \
  "$TELEGRAM_BOT_TOKEN" \
  "$TELEGRAM_CHAT_ID" \
  "$PROJ_ROOT" \
  "$CLAUDE_BIN" \
  "$OFFSET" \
  "$LOG_FILE" \
  "$UPDATES_JSON" \
  << 'PYEOF'
import sys
import json
import subprocess
import urllib.request
import urllib.parse
import datetime
import re
import glob
import shutil
import os

bot_token   = sys.argv[1]
chat_id     = sys.argv[2]
proj_root   = sys.argv[3]
claude_bin  = sys.argv[4]
current_offset = int(sys.argv[5])
log_file    = sys.argv[6]
updates_raw = sys.argv[7]

API_BASE = f"https://api.telegram.org/bot{bot_token}"

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    with open(log_file, "a") as f:
        f.write(line)

def tg_send(text, parse_mode="HTML"):
    """Send a message to the authorized chat via urllib (no shell injection possible)."""
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            pass
    except Exception as e:
        log(f"tg_send failed: {e}")

try:
    data = json.loads(updates_raw)
except Exception as e:
    log(f"Failed to parse getUpdates response: {e}")
    print(current_offset)
    sys.exit(0)

if not data.get("ok"):
    log("getUpdates returned ok=false")
    print(current_offset)
    sys.exit(0)

updates = data.get("result", [])
new_offset = current_offset

for update in updates:
    update_id = update.get("update_id", 0)
    # Track highest update_id+1 regardless of whether we process it
    if update_id + 1 > new_offset:
        new_offset = update_id + 1

    msg = update.get("message")
    if not msg:
        continue

    text = msg.get("text")
    if not text:
        continue

    # Security: only process messages from the authorized chat
    from_chat = str(msg.get("chat", {}).get("id", ""))
    if from_chat != str(chat_id):
        log(f"Ignoring message from unauthorized chat_id={from_chat}")
        continue

    log(f"Received message: {text[:120]!r}")

    # promote <short-id> — install a skill draft to ~/.claude/skills/
    promote_match = re.match(r'^promote\s+([a-f0-9]{6,32})\s*$', text.strip(), re.IGNORECASE)
    if promote_match:
        skill_id = promote_match.group(1)
        matches = glob.glob(os.path.join(proj_root, 'state', 'skill-drafts', f'{skill_id}*-skill-draft.md'))
        if not matches:
            log(f"promote: no draft found for id={skill_id}")
            tg_send(f"❌ No draft found for <code>{skill_id}</code>.")
            continue
        draft_path = matches[0]
        skill_name = None
        with open(draft_path, encoding='utf-8') as f:
            in_fm = False
            for line in f:
                line = line.rstrip()
                if line == '---':
                    in_fm = not in_fm
                    continue
                if in_fm and line.startswith('name:'):
                    skill_name = line.split(':', 1)[1].strip()
                    break
        if not skill_name:
            log(f"promote: could not parse name from {draft_path}")
            tg_send(f"❌ Could not parse <code>name:</code> from draft <code>{skill_id}</code>.")
            continue
        skill_dir = os.path.join(os.path.expanduser('~/.claude/skills'), skill_name)
        os.makedirs(skill_dir, exist_ok=True)
        dest = os.path.join(skill_dir, 'SKILL.md')
        shutil.copy2(draft_path, dest)
        log(f"promote: '{skill_name}' → {dest} — sending Telegram confirmation")
        tg_send(f"✅ Skill <b>{skill_name}</b> promoted.")
        continue

    # Acknowledge receipt
    tg_send("⏳ Running…")

    # Run claude — message text passed as argv element, NEVER shell-interpolated
    try:
        result = subprocess.run(
            [
                claude_bin,
                "--dangerously-skip-permissions",
                "--print",
                "-p",
                text,          # ← safe: subprocess arg list, not shell string
            ],
            cwd=proj_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        response = result.stdout.strip() or result.stderr.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        response = "⚠️ Claude timed out after 120 seconds."
        log("claude timed out")
    except Exception as e:
        response = f"⚠️ Error running Claude: {e}"
        log(f"claude error: {e}")

    # Truncate to Telegram's 4096-char limit
    if len(response) > 4096:
        response = response[:4096]

    log(f"Sending response ({len(response)} chars)")
    tg_send(response)

print(new_offset)
PYEOF
)

# Write updated offset back
printf '%s' "$NEW_OFFSET" > "$OFFSET_FILE"
log "Offset updated to ${NEW_OFFSET}"

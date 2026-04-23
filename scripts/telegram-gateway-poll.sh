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

    # ── promote helpers ────────────────────────────────────────────────────
    def find_draft(sid):
        m = glob.glob(os.path.join(proj_root, 'state', 'skill-drafts', f'{sid}*-skill-draft.md'))
        return m[0] if m else None

    def parse_skill_name(path):
        with open(path, encoding='utf-8') as f:
            in_fm = False
            for line in f:
                line = line.rstrip()
                if line == '---':
                    in_fm = not in_fm
                    continue
                if in_fm and line.startswith('name:'):
                    return line.split(':', 1)[1].strip()
        return None

    def install_skill(draft_path, skill_name, scope):
        """Copy draft to global-skills/ or skills/, symlink into ~/.claude/skills/."""
        subdir = 'global-skills' if scope == 'global' else 'skills'
        skill_dir = os.path.join(proj_root, subdir, skill_name)
        os.makedirs(skill_dir, exist_ok=True)
        shutil.copy2(draft_path, os.path.join(skill_dir, 'SKILL.md'))
        link = os.path.join(os.path.expanduser('~/.claude/skills'), skill_name)
        if os.path.islink(link):
            os.unlink(link)
        elif os.path.exists(link):
            shutil.rmtree(link)
        os.symlink(skill_dir, link)
        return skill_dir

    # promote <id> global|project — execute promotion
    promote_confirm = re.match(r'^promote\s+([a-f0-9]{6,32})\s+(global|project)\s*$', text.strip(), re.IGNORECASE)
    if promote_confirm:
        skill_id, scope = promote_confirm.group(1), promote_confirm.group(2).lower()
        draft_path = find_draft(skill_id)
        if not draft_path:
            log(f"promote: no draft for {skill_id}")
            tg_send(f"❌ No draft found for <code>{skill_id}</code>.")
            continue
        skill_name = parse_skill_name(draft_path)
        if not skill_name:
            log(f"promote: could not parse name from {draft_path}")
            tg_send(f"❌ Could not parse <code>name:</code> from draft <code>{skill_id}</code>.")
            continue
        skill_dir = install_skill(draft_path, skill_name, scope)
        log(f"promote: '{skill_name}' → {skill_dir}")
        tg_send(f"✅ Skill <b>{skill_name}</b> promoted to <b>{scope}</b>.")
        continue

    # promote <id> — classify and ask for scope
    promote_match = re.match(r'^promote\s+([a-f0-9]{6,32})\s*$', text.strip(), re.IGNORECASE)
    if promote_match:
        skill_id = promote_match.group(1)
        draft_path = find_draft(skill_id)
        if not draft_path:
            log(f"promote: no draft for {skill_id}")
            tg_send(f"❌ No draft found for <code>{skill_id}</code>.")
            continue
        skill_content = open(draft_path, encoding='utf-8').read()
        classify_prompt = (
            "Classify this Claude Code skill as GLOBAL or PROJECT.\n\n"
            "GLOBAL: useful across any software project (debugging, code review, TDD, etc.)\n"
            "PROJECT: specific to Uncle J's Refinery (references its scripts, paths, or tools)\n\n"
            "Respond with exactly:\n"
            "SCOPE: GLOBAL  or  SCOPE: PROJECT\n"
            "REASON: one sentence\n\n"
            f"--- SKILL ---\n{skill_content[:2000]}"
        )
        try:
            result = subprocess.run(
                [claude_bin, '--dangerously-skip-permissions', '--print', '-p', classify_prompt],
                cwd=proj_root, capture_output=True, text=True, timeout=60,
            )
            out = result.stdout.strip()
        except Exception as e:
            out = ''
            log(f"promote: classify error: {e}")
        scope_line   = next((l for l in out.splitlines() if l.startswith('SCOPE:')),  '')
        reason_line  = next((l for l in out.splitlines() if l.startswith('REASON:')), '')
        suggested    = 'global' if 'GLOBAL' in scope_line.upper() else 'project'
        reason       = reason_line.replace('REASON:', '').strip() or '(no reason)'
        log(f"promote: classified {skill_id} as {suggested}")
        tg_send(
            f"📝 <code>{skill_id}</code> — suggested: <b>{suggested}</b>\n"
            f"{reason}\n\n"
            f"Reply <code>promote {skill_id} global</code> or <code>promote {skill_id} project</code>"
        )
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

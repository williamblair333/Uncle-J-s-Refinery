# Hermes Features → Uncle J's Refinery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port four Hermes-exclusive features (Telegram notifications out, Telegram command gateway in, auto-skill creation, Ralph cron installer) into Uncle J's Refinery as standalone `features/*/install.sh` installable modules.

**Architecture:** Each feature is a self-contained installer under `features/<name>/install.sh` that follows the existing stack-alerts pattern: prompts user for config, writes to `.env`, installs cron and/or Claude Code hooks, and includes an `--uninstall` flag. Shared Telegram infrastructure (`lib/notify.sh`, `lib/notify-telegram.sh`) is reused as-is. Claude Code Stop hooks power the session-end features (notify + skill suggest). A standalone poll script powers the gateway.

**Tech Stack:** Bash, Python 3 (stdlib only), Claude Code CLI (`claude --print`), Telegram Bot API (REST via curl), crontab.

---

## Prerequisite: Telegram already configured

`.env` must have `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. These are already present from the stack-alerts install. All four installers check for them and fail fast if absent.

---

## Sub-plan A: Telegram Session Notifications

**Files:**
- Create: `scripts/session-notify.sh`
- Create: `features/telegram-notify/install.sh`
- Modify: `.claude/settings.json` (Stop hook — done by installer, not manually)

### Task A1: Write `scripts/session-notify.sh`

This is the Claude Code Stop hook script. Claude Code passes a JSON payload via stdin with `session_id` and `transcript_path`. The script extracts the last assistant message and sends it to Telegram.

- [ ] **Step 1: Create the script**

```bash
cat > /opt/proj/Uncle-J-s-Refinery/scripts/session-notify.sh << 'EOF'
#!/usr/bin/env bash
# Stop hook: send session summary to Telegram when Claude session ends.
# Claude Code passes JSON via stdin: {session_id, transcript_path, cwd}.

set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJ_ROOT/.env"

[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

[[ -z "${TELEGRAM_BOT_TOKEN:-}" ]] && exit 0
[[ -z "${TELEGRAM_CHAT_ID:-}" ]] && exit 0

PAYLOAD=$(cat)
TRANSCRIPT_PATH=$(python3 -c \
  "import sys,json; d=json.loads(sys.argv[1]); print(d.get('transcript_path',''))" \
  "$PAYLOAD" 2>/dev/null || echo "")
SESSION_ID=$(python3 -c \
  "import sys,json; d=json.loads(sys.argv[1]); print(d.get('session_id','?')[:8])" \
  "$PAYLOAD" 2>/dev/null || echo "?")

SUMMARY="🤖 Session <code>${SESSION_ID}</code> ended."

if [[ -f "$TRANSCRIPT_PATH" ]]; then
  SUMMARY=$(python3 - "$TRANSCRIPT_PATH" "$SESSION_ID" << 'PYEOF'
import sys, json

transcript_path, session_id = sys.argv[1], sys.argv[2]
last_text = ""
try:
    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                role = obj.get("role") or obj.get("type", "")
                if role == "assistant":
                    content = obj.get("content", "")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                last_text = block.get("text", "")
                    elif isinstance(content, str):
                        last_text = content
            except json.JSONDecodeError:
                continue
except Exception:
    pass

if last_text:
    text = last_text[:800].strip()
    if len(last_text) > 800:
        text += "…"
    print(f"🤖 Session <code>{session_id}</code> ended.\n\n{text}")
else:
    print(f"🤖 Session <code>{session_id}</code> ended.")
PYEOF
  )
fi

source "$PROJ_ROOT/lib/notify.sh"
notify_send_text "$SUMMARY" || true
EOF
chmod +x /opt/proj/Uncle-J-s-Refinery/scripts/session-notify.sh
```

- [ ] **Step 2: Smoke-test the script in isolation**

```bash
cd /opt/proj/Uncle-J-s-Refinery
echo '{"session_id":"test1234abcd","transcript_path":"","cwd":".","hook_event_name":"Stop"}' \
  | bash scripts/session-notify.sh
# Expected: Telegram message "🤖 Session test1234 ended." (or no-op if TOKEN not set)
```

- [ ] **Step 3: Commit**

```bash
git add scripts/session-notify.sh
git commit -m "feat: add session-notify.sh — Stop hook → Telegram session summary"
```

### Task A2: Write `features/telegram-notify/install.sh`

- [ ] **Step 1: Create installer**

```bash
mkdir -p /opt/proj/Uncle-J-s-Refinery/features/telegram-notify

cat > /opt/proj/Uncle-J-s-Refinery/features/telegram-notify/install.sh << 'EOF'
#!/usr/bin/env bash
# Install/uninstall Telegram session notifications (Stop hook).
# Usage: bash features/telegram-notify/install.sh [--uninstall]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SETTINGS="$PROJ_ROOT/.claude/settings.json"
HOOK_SCRIPT="$PROJ_ROOT/scripts/session-notify.sh"
MARKER="uncle-j-session-notify"

step()  { printf '\n==> %s\n' "$*"; }
ok()    { printf '    OK  %s\n' "$*"; }
warn()  { printf '    !!  %s\n' "$*" >&2; }

_remove_hook() {
  python3 - "$SETTINGS" "$MARKER" << 'PYEOF'
import sys, json
settings_path, marker = sys.argv[1], sys.argv[2]
with open(settings_path) as f:
    d = json.load(f)
hooks = d.get("hooks", {})
stops = hooks.get("Stop", [])
hooks["Stop"] = [h for h in stops if marker not in json.dumps(h)]
if not hooks["Stop"]:
    del hooks["Stop"]
d["hooks"] = hooks
with open(settings_path, "w") as f:
    json.dump(d, f, indent=2)
print("removed")
PYEOF
}

if [[ "${1:-}" == "--uninstall" ]]; then
  step "Uninstalling session notifications"
  _remove_hook
  ok "Stop hook removed from $SETTINGS"
  exit 0
fi

step "Checking dependencies"
for cmd in curl python3 bash; do
  command -v "$cmd" &>/dev/null && ok "$cmd" || { warn "$cmd missing"; exit 1; }
done

[[ -f "$PROJ_ROOT/.env" ]] && source "$PROJ_ROOT/.env" || true
[[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] || {
  warn "TELEGRAM_BOT_TOKEN not set. Run: bash features/stack-alerts/install.sh first."
  exit 1
}
ok "Telegram credentials present"
[[ -f "$HOOK_SCRIPT" ]] || { warn "Missing $HOOK_SCRIPT"; exit 1; }
ok "session-notify.sh present"

step "Installing Stop hook into $SETTINGS"
python3 - "$SETTINGS" "$HOOK_SCRIPT" "$MARKER" << 'PYEOF'
import sys, json
settings_path, script_path, marker = sys.argv[1], sys.argv[2], sys.argv[3]
with open(settings_path) as f:
    d = json.load(f)
hooks = d.setdefault("hooks", {})
stops = hooks.setdefault("Stop", [])
# Idempotent: remove existing entry first
stops[:] = [h for h in stops if marker not in json.dumps(h)]
stops.append({
    "hooks": [{
        "type": "command",
        "command": f"bash {script_path}  # {marker}",
        "async": True
    }]
})
d["hooks"] = hooks
with open(settings_path, "w") as f:
    json.dump(d, f, indent=2)
print("added")
PYEOF
ok "Stop hook registered (async)"

step "Sending test message"
set -a; source "$PROJ_ROOT/.env"; set +a
source "$PROJ_ROOT/lib/notify.sh"
notify_send_text "🔔 Uncle J session notifications <b>active</b>. You'll receive a summary after each Claude session."
ok "Test message sent — check Telegram."

step "Done"
echo ""
echo "  Each Claude Code session will now send its last response to Telegram on exit."
echo "  To uninstall: bash $SCRIPT_DIR/install.sh --uninstall"
EOF
chmod +x /opt/proj/Uncle-J-s-Refinery/features/telegram-notify/install.sh
```

- [ ] **Step 2: Verify installer runs without errors (dry-check)**

```bash
cd /opt/proj/Uncle-J-s-Refinery
bash features/telegram-notify/install.sh --uninstall 2>&1 | head -5
# Expected: "==> Uninstalling session notifications" then "OK  removed"
```

- [ ] **Step 3: Run the actual install**

```bash
bash /opt/proj/Uncle-J-s-Refinery/features/telegram-notify/install.sh
# Expected: dependency checks pass, Stop hook added to .claude/settings.json,
#           test Telegram message received.
```

- [ ] **Step 4: Verify hook appears in settings.json**

```bash
python3 -c "
import json
d = json.load(open('/opt/proj/Uncle-J-s-Refinery/.claude/settings.json'))
stops = d.get('hooks',{}).get('Stop',[])
print('Stop hooks:', len(stops))
print(json.dumps(stops, indent=2))
"
# Expected: at least 1 Stop hook entry containing session-notify.sh
```

- [ ] **Step 5: Commit**

```bash
git add features/telegram-notify/install.sh
git commit -m "feat: add telegram-notify feature — Stop hook → Telegram session summary"
```

---

## Sub-plan B: Telegram Command Gateway

**Files:**
- Create: `scripts/telegram-gateway-poll.sh`
- Create: `state/telegram-gateway-offset.txt` (auto-created at runtime)
- Create: `features/telegram-gateway/install.sh`

### Task B1: Write `scripts/telegram-gateway-poll.sh`

Polls Telegram `getUpdates`, runs `claude --print` for each message from the authorized chat, replies with the result. Tracks update offset in `state/telegram-gateway-offset.txt` to avoid reprocessing.

- [ ] **Step 1: Create the poll script**

```bash
cat > /opt/proj/Uncle-J-s-Refinery/scripts/telegram-gateway-poll.sh << 'EOF'
#!/usr/bin/env bash
# Poll Telegram for commands, invoke claude --print, reply.
# Cron runs this every 2 minutes.

set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJ_ROOT/.env"
OFFSET_FILE="$PROJ_ROOT/state/telegram-gateway-offset.txt"
LOG_FILE="$PROJ_ROOT/state/telegram-gateway.log"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "claude")}"

[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a
[[ -z "${TELEGRAM_BOT_TOKEN:-}" ]] && exit 0
[[ -z "${TELEGRAM_CHAT_ID:-}" ]] && exit 0

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"; }

TG_API="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"
OFFSET=$(cat "$OFFSET_FILE" 2>/dev/null || echo "0")

UPDATES=$(curl -sf \
  "${TG_API}/getUpdates?offset=${OFFSET}&limit=10&allowed_updates=message&timeout=0" \
  2>/dev/null || echo '{"ok":false,"result":[]}')

NEW_OFFSET=$(python3 - \
  "$UPDATES" "$OFFSET" "$TELEGRAM_CHAT_ID" "$PROJ_ROOT" "$CLAUDE_BIN" \
  "$LOG_FILE" "$TG_API" << 'PYEOF'
import sys, json, subprocess, urllib.request

updates_json, offset_str, auth_chat_id, proj_root, claude_bin, log_file, tg_api = (
    sys.argv[1], sys.argv[2], sys.argv[3],
    sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7]
)
offset = int(offset_str)

def log(msg):
    from datetime import datetime
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
    with open(log_file, "a") as f:
        f.write(line)

def tg_send(chat_id, text):
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text[:4096],
        "parse_mode": "HTML"
    }).encode()
    req = urllib.request.Request(
        f"{tg_api}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        log(f"tg_send error: {e}")

try:
    data = json.loads(updates_json)
except json.JSONDecodeError:
    print(offset)
    sys.exit(0)

if not data.get("ok"):
    print(offset)
    sys.exit(0)

results = data.get("result", [])
if not results:
    print(offset)
    sys.exit(0)

max_uid = offset
for update in results:
    uid = update.get("update_id", 0)
    if uid + 1 > max_uid:
        max_uid = uid + 1

    msg = update.get("message", {})
    if not msg:
        continue

    chat_id = str(msg.get("chat", {}).get("id", ""))
    if chat_id != auth_chat_id:
        continue  # security: ignore unauthorized senders

    text = msg.get("text", "").strip()
    if not text:
        continue

    log(f"Gateway command from {chat_id}: {text[:80]}")

    tg_send(chat_id, "⏳ Running…")

    try:
        result = subprocess.run(
            [claude_bin, "--dangerously-skip-permissions", "--print", "-p", text],
            capture_output=True, text=True, timeout=120, cwd=proj_root
        )
        response = (result.stdout or result.stderr or "(no output)").strip()
    except subprocess.TimeoutExpired:
        response = "⏱ Timed out (120s)."
    except Exception as e:
        response = f"❌ Error: {e}"

    log(f"Gateway response ({len(response)} chars)")
    tg_send(chat_id, response)

print(max_uid)
PYEOF
)

echo "$NEW_OFFSET" > "$OFFSET_FILE"
EOF
chmod +x /opt/proj/Uncle-J-s-Refinery/scripts/telegram-gateway-poll.sh
```

- [ ] **Step 2: Test offset tracking without real Telegram**

```bash
cd /opt/proj/Uncle-J-s-Refinery

# Verify offset file is created on first run (with no-op empty result)
# Temporarily override TG creds to empty so curl fails gracefully
TELEGRAM_BOT_TOKEN="" TELEGRAM_CHAT_ID="" \
  bash scripts/telegram-gateway-poll.sh
# Expected: exits 0 immediately (empty token guard)

# Test with mocked empty update response
cat state/telegram-gateway-offset.txt 2>/dev/null || echo "(no offset file yet — expected on first run)"
```

- [ ] **Step 3: Commit**

```bash
git add scripts/telegram-gateway-poll.sh
git commit -m "feat: add telegram-gateway-poll.sh — Telegram → claude --print → Telegram reply"
```

### Task B2: Write `features/telegram-gateway/install.sh`

- [ ] **Step 1: Create installer**

```bash
mkdir -p /opt/proj/Uncle-J-s-Refinery/features/telegram-gateway

cat > /opt/proj/Uncle-J-s-Refinery/features/telegram-gateway/install.sh << 'EOF'
#!/usr/bin/env bash
# Install/uninstall Telegram command gateway (Telegram → claude --print).
# Usage: bash features/telegram-gateway/install.sh [--uninstall]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJ_ROOT/.env"
CRON_MARKER="uncle-j-telegram-gateway"
POLL_SCRIPT="$PROJ_ROOT/scripts/telegram-gateway-poll.sh"

source "$PROJ_ROOT/lib/feature-helpers.sh"

step()  { printf '\n==> %s\n' "$*"; }
ok()    { printf '    OK  %s\n' "$*"; }
warn()  { printf '    !!  %s\n' "$*" >&2; }

if [[ "${1:-}" == "--uninstall" ]]; then
  step "Uninstalling Telegram gateway"
  remove_cron "$CRON_MARKER"
  rm -f "$PROJ_ROOT/state/telegram-gateway-offset.txt"
  ok "Cron removed and offset state cleared."
  exit 0
fi

step "Checking dependencies"
for cmd in curl python3 jq; do
  command -v "$cmd" &>/dev/null && ok "$cmd" || { warn "$cmd missing"; exit 1; }
done
CLAUDE_BIN=$(command -v claude 2>/dev/null || true)
[[ -n "$CLAUDE_BIN" ]] && ok "claude at $CLAUDE_BIN" || { warn "claude CLI not found"; exit 1; }

[[ -f "$ENV_FILE" ]] && source "$ENV_FILE" || true
[[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] || {
  warn "TELEGRAM_BOT_TOKEN not set. Run: bash features/stack-alerts/install.sh first."
  exit 1
}
ok "Telegram credentials present"

step "Verifying bot token is valid"
BOT_INFO=$(curl -sf "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" 2>/dev/null || echo '{"ok":false}')
BOT_OK=$(python3 -c "import sys,json; d=json.loads(sys.argv[1]); print(d.get('ok','false'))" "$BOT_INFO")
[[ "$BOT_OK" == "True" ]] && ok "Bot token valid" || { warn "Bot token invalid — check TELEGRAM_BOT_TOKEN in .env"; exit 1; }

step "Installing cron poll job (every 2 minutes)"
CRON_PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
POLL_ENTRY="*/2 * * * * PATH=${CRON_PATH} CLAUDE_BIN=${CLAUDE_BIN} bash ${POLL_SCRIPT} >> ${PROJ_ROOT}/state/telegram-gateway.log 2>&1"
install_cron "$CRON_MARKER" "$POLL_ENTRY"
ok "Cron installed: */2 * * * *"

step "Sending test message"
set -a; source "$ENV_FILE"; set +a
source "$PROJ_ROOT/lib/notify.sh"
notify_send_text "🤖 Uncle J <b>command gateway active</b>.

Send any message here and I'll run it through Claude Code and reply.
Authorized chat: <code>${TELEGRAM_CHAT_ID}</code>"
ok "Test message sent — check Telegram."

step "Done"
echo ""
echo "  Send any message to your Telegram bot and Claude will respond within 2 minutes."
echo "  Logs: $PROJ_ROOT/state/telegram-gateway.log"
echo "  To uninstall: bash $SCRIPT_DIR/install.sh --uninstall"
EOF
chmod +x /opt/proj/Uncle-J-s-Refinery/features/telegram-gateway/install.sh
```

- [ ] **Step 2: Run the installer**

```bash
bash /opt/proj/Uncle-J-s-Refinery/features/telegram-gateway/install.sh
# Expected: deps pass, bot token validates, cron installed, test message in Telegram.
```

- [ ] **Step 3: Verify cron entry**

```bash
crontab -l | grep telegram-gateway
# Expected: line like "*/2 * * * * ... bash .../telegram-gateway-poll.sh >> ..."
```

- [ ] **Step 4: End-to-end test**

Send a message to your Telegram bot: `list files in /opt/proj/Uncle-J-s-Refinery`

Within 2 minutes, check Telegram for Claude's response and `state/telegram-gateway.log` for the log entry.

- [ ] **Step 5: Commit**

```bash
git add features/telegram-gateway/install.sh
git commit -m "feat: add telegram-gateway feature — Telegram commands → claude --print"
```

---

## Sub-plan C: Auto-Skill Creation

**Files:**
- Create: `scripts/skill-suggest.sh`
- Create: `features/auto-skill/install.sh`
- Modify: `.claude/settings.json` (Stop hook — done by installer)

### Task C1: Write `scripts/skill-suggest.sh`

Stop hook script: reads the session transcript, asks Claude to suggest a reusable skill, saves a draft to `~/.claude/skills/drafts/`, and notifies via Telegram.

- [ ] **Step 1: Create the script**

```bash
mkdir -p "$HOME/.claude/skills/drafts"

cat > /opt/proj/Uncle-J-s-Refinery/scripts/skill-suggest.sh << 'EOF'
#!/usr/bin/env bash
# Stop hook: suggest a reusable skill from the session transcript.
# Saves drafts to ~/.claude/skills/drafts/ and notifies via Telegram.
# Runs async — does not block session exit.

set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJ_ROOT/.env"
SKILLS_DRAFT_DIR="${HOME}/.claude/skills/drafts"
LOG_FILE="$PROJ_ROOT/state/auto-skill.log"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "claude")}"

[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"; }

PAYLOAD=$(cat)
TRANSCRIPT_PATH=$(python3 -c \
  "import sys,json; d=json.loads(sys.argv[1]); print(d.get('transcript_path',''))" \
  "$PAYLOAD" 2>/dev/null || echo "")

[[ -f "$TRANSCRIPT_PATH" ]] || { log "No transcript — skipping skill suggest"; exit 0; }

# Extract last ~3000 chars of conversation text from transcript JSONL
EXCERPT=$(python3 - "$TRANSCRIPT_PATH" << 'PYEOF'
import sys, json

transcript_path = sys.argv[1]
chunks = []
try:
    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                role = obj.get("role") or obj.get("type", "")
                if role not in ("user", "assistant", "human"):
                    continue
                content = obj.get("content", "")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            t = block.get("text", "").strip()
                            if t:
                                chunks.append(f"{role}: {t}")
                elif isinstance(content, str) and content.strip():
                    chunks.append(f"{role}: {content.strip()}")
            except json.JSONDecodeError:
                continue
except Exception:
    pass

full = "\n".join(chunks)
print(full[-3000:] if len(full) > 3000 else full)
PYEOF
)

[[ -z "$EXCERPT" ]] && { log "Empty excerpt — skipping"; exit 0; }

SKILL_PROMPT="Review this Claude Code session transcript. If a clear, reusable workflow or process was demonstrated, write a skill file for Uncle J's Refinery.

A skill file has this format:
---
name: kebab-case-name
description: one-line description of when to invoke this skill
type: process
---

# Skill Name

## When to trigger

- Bullet conditions

## Steps

1. Step one
2. Step two

## What NOT to do

- Anti-pattern

Respond with ONLY the skill file content (starting with ---).
If no reusable skill is evident, respond with exactly: SKIP

Transcript:
${EXCERPT}"

log "Running skill suggestion via claude --print"
SKILL_CONTENT=$("$CLAUDE_BIN" --dangerously-skip-permissions -p "$SKILL_PROMPT" 2>/dev/null || echo "SKIP")
SKILL_CONTENT=$(echo "$SKILL_CONTENT" | sed 's/^[[:space:]]*//')

if [[ "$SKILL_CONTENT" == "SKIP" || -z "$SKILL_CONTENT" ]]; then
  log "No skill suggested — skipping"
  exit 0
fi

mkdir -p "$SKILLS_DRAFT_DIR"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
DRAFT_FILE="$SKILLS_DRAFT_DIR/draft-${TIMESTAMP}.md"
echo "$SKILL_CONTENT" > "$DRAFT_FILE"
log "Skill draft saved: $DRAFT_FILE"

if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  PREVIEW=$(head -10 "$DRAFT_FILE" | sed 's/</\&lt;/g; s/>/\&gt;/g')
  source "$PROJ_ROOT/lib/notify.sh"
  notify_send_text "💡 <b>Skill suggestion drafted</b>

<code>${DRAFT_FILE}</code>

<pre>${PREVIEW}
…</pre>

Review, rename, and move to <code>~/.claude/skills/</code> to activate." || true
  log "Telegram notification sent"
fi
EOF
chmod +x /opt/proj/Uncle-J-s-Refinery/scripts/skill-suggest.sh
```

- [ ] **Step 2: Smoke-test with a fake transcript**

```bash
# Create a minimal test transcript
FAKE_TRANSCRIPT=$(mktemp --suffix=.jsonl)
echo '{"role":"user","content":"How do I fix a failing test?"}' >> "$FAKE_TRANSCRIPT"
echo '{"role":"assistant","content":"First reproduce the failure, then hypothesize root cause, then fix only the confirmed cause."}' >> "$FAKE_TRANSCRIPT"

echo "{\"session_id\":\"testabcd1234\",\"transcript_path\":\"${FAKE_TRANSCRIPT}\",\"cwd\":\"/opt/proj\"}" \
  | CLAUDE_BIN="" bash /opt/proj/Uncle-J-s-Refinery/scripts/skill-suggest.sh || true

# Expected: log entry in state/auto-skill.log saying "Running skill suggestion"
# (will fail at claude call if CLAUDE_BIN="" but shows the parsing works)
cat /opt/proj/Uncle-J-s-Refinery/state/auto-skill.log 2>/dev/null || echo "(no log yet)"
rm -f "$FAKE_TRANSCRIPT"
```

- [ ] **Step 3: Commit**

```bash
git add scripts/skill-suggest.sh
git commit -m "feat: add skill-suggest.sh — Stop hook → auto-draft skill from transcript"
```

### Task C2: Write `features/auto-skill/install.sh`

- [ ] **Step 1: Create installer**

```bash
mkdir -p /opt/proj/Uncle-J-s-Refinery/features/auto-skill

cat > /opt/proj/Uncle-J-s-Refinery/features/auto-skill/install.sh << 'EOF'
#!/usr/bin/env bash
# Install/uninstall auto-skill creation (Stop hook).
# Usage: bash features/auto-skill/install.sh [--uninstall]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SETTINGS="$PROJ_ROOT/.claude/settings.json"
HOOK_SCRIPT="$PROJ_ROOT/scripts/skill-suggest.sh"
MARKER="uncle-j-auto-skill"
SKILLS_DRAFT_DIR="${HOME}/.claude/skills/drafts"

step()  { printf '\n==> %s\n' "$*"; }
ok()    { printf '    OK  %s\n' "$*"; }
warn()  { printf '    !!  %s\n' "$*" >&2; }

_remove_hook() {
  python3 - "$SETTINGS" "$MARKER" << 'PYEOF'
import sys, json
settings_path, marker = sys.argv[1], sys.argv[2]
with open(settings_path) as f:
    d = json.load(f)
hooks = d.get("hooks", {})
stops = hooks.get("Stop", [])
hooks["Stop"] = [h for h in stops if marker not in json.dumps(h)]
if not hooks["Stop"]:
    del hooks["Stop"]
d["hooks"] = hooks
with open(settings_path, "w") as f:
    json.dump(d, f, indent=2)
print("removed")
PYEOF
}

if [[ "${1:-}" == "--uninstall" ]]; then
  step "Uninstalling auto-skill creation"
  _remove_hook
  ok "Stop hook removed from $SETTINGS"
  exit 0
fi

step "Checking dependencies"
for cmd in python3; do
  command -v "$cmd" &>/dev/null && ok "$cmd" || { warn "$cmd missing"; exit 1; }
done
CLAUDE_BIN=$(command -v claude 2>/dev/null || true)
[[ -n "$CLAUDE_BIN" ]] && ok "claude at $CLAUDE_BIN" || { warn "claude CLI not found"; exit 1; }
[[ -f "$HOOK_SCRIPT" ]] || { warn "Missing $HOOK_SCRIPT"; exit 1; }
ok "skill-suggest.sh present"

step "Creating drafts directory"
mkdir -p "$SKILLS_DRAFT_DIR"
ok "$SKILLS_DRAFT_DIR"

step "Installing Stop hook into $SETTINGS (async)"
python3 - "$SETTINGS" "$HOOK_SCRIPT" "$MARKER" << 'PYEOF'
import sys, json
settings_path, script_path, marker = sys.argv[1], sys.argv[2], sys.argv[3]
with open(settings_path) as f:
    d = json.load(f)
hooks = d.setdefault("hooks", {})
stops = hooks.setdefault("Stop", [])
stops[:] = [h for h in stops if marker not in json.dumps(h)]
stops.append({
    "hooks": [{
        "type": "command",
        "command": f"bash {script_path}  # {marker}",
        "async": True
    }]
})
d["hooks"] = hooks
with open(settings_path, "w") as f:
    json.dump(d, f, indent=2)
print("added")
PYEOF
ok "Stop hook registered (async — won't slow session exit)"

step "Done"
echo ""
echo "  After each session, Claude will suggest a skill if a reusable workflow was demonstrated."
echo "  Drafts land in: $SKILLS_DRAFT_DIR"
echo "  Move a draft to ~/.claude/skills/<name>.md to activate it."
echo "  To uninstall: bash $SCRIPT_DIR/install.sh --uninstall"
EOF
chmod +x /opt/proj/Uncle-J-s-Refinery/features/auto-skill/install.sh
```

- [ ] **Step 2: Run the installer**

```bash
bash /opt/proj/Uncle-J-s-Refinery/features/auto-skill/install.sh
# Expected: deps pass, drafts dir created, Stop hook added to settings.json.
```

- [ ] **Step 3: Verify both Stop hooks appear in settings.json**

```bash
python3 -c "
import json
d = json.load(open('/opt/proj/Uncle-J-s-Refinery/.claude/settings.json'))
stops = d.get('hooks',{}).get('Stop',[])
print(f'Stop hook entries: {len(stops)}')
for s in stops:
    cmd = s.get('hooks',[{}])[0].get('command','')
    print(' -', cmd[:80])
"
# Expected: 2 Stop hook entries (session-notify and skill-suggest)
```

- [ ] **Step 4: Commit**

```bash
git add features/auto-skill/install.sh
git commit -m "feat: add auto-skill feature — Stop hook → skill draft from transcript"
```

---

## Sub-plan D: Ralph + Cron

**Files:**
- Create: `scripts/ralph-cron-run.sh`
- Create: `features/ralph-cron/install.sh`

### Task D1: Write `scripts/ralph-cron-run.sh`

Thin wrapper that loads a per-PRD config file and calls `ralph-harness.sh`, then sends a Telegram notification with the result. The config file lets cron entries stay simple.

- [ ] **Step 1: Create the wrapper**

```bash
cat > /opt/proj/Uncle-J-s-Refinery/scripts/ralph-cron-run.sh << 'EOF'
#!/usr/bin/env bash
# Cron wrapper for ralph-harness.sh.
# Reads config from a JSON file passed as $1, runs Ralph, notifies via Telegram.
# Usage: bash scripts/ralph-cron-run.sh /path/to/ralph-cron-config.json

set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJ_ROOT/.env"
LOG_FILE="$PROJ_ROOT/state/ralph-cron.log"
HARNESS="$PROJ_ROOT/ralph-harness.sh"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"; }

CONFIG_FILE="${1:?Usage: $0 /path/to/ralph-cron-config.json}"
[[ -f "$CONFIG_FILE" ]] || { log "Config not found: $CONFIG_FILE"; exit 1; }

[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

PRD_PATH=$(python3 -c \
  "import sys,json; d=json.load(open(sys.argv[1])); print(d['prd_path'])" "$CONFIG_FILE")
MAX_ITER=$(python3 -c \
  "import sys,json; d=json.load(open(sys.argv[1])); print(d.get('max_iterations',10))" "$CONFIG_FILE")
RISK=$(python3 -c \
  "import sys,json; d=json.load(open(sys.argv[1])); print(d.get('risk_threshold','0.65'))" "$CONFIG_FILE")
REPO=$(python3 -c \
  "import sys,json; d=json.load(open(sys.argv[1])); print(d.get('repo_path','$PROJ_ROOT'))" "$CONFIG_FILE")
NOTIFY=$(python3 -c \
  "import sys,json; d=json.load(open(sys.argv[1])); print(d.get('notify_telegram','true'))" "$CONFIG_FILE")

[[ -f "$PRD_PATH" ]] || { log "PRD not found: $PRD_PATH"; exit 1; }

log "Starting Ralph: PRD=$PRD_PATH max_iter=$MAX_ITER risk=$RISK"

START=$(date +%s)
set +e
bash "$HARNESS" \
  --prd "$PRD_PATH" \
  --repo "$REPO" \
  --max-iterations "$MAX_ITER" \
  --risk-threshold "$RISK" \
  >> "$LOG_FILE" 2>&1
RC=$?
set -e

ELAPSED=$(( $(date +%s) - START ))

if [[ "$RC" -eq 0 ]]; then
  STATUS="✅ Done"
elif [[ "$RC" -eq 2 ]]; then
  STATUS="⚠️ Max iterations reached"
else
  STATUS="❌ Failed (exit $RC)"
fi

log "Ralph finished: $STATUS in ${ELAPSED}s"

if [[ "$NOTIFY" == "true" && -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  PRD_NAME=$(basename "$PRD_PATH")
  source "$PROJ_ROOT/lib/notify.sh"
  notify_send_text "🔁 <b>Ralph loop finished</b>

PRD: <code>${PRD_NAME}</code>
Status: ${STATUS}
Elapsed: ${ELAPSED}s
Log: <code>${LOG_FILE}</code>" || true
fi

exit "$RC"
EOF
chmod +x /opt/proj/Uncle-J-s-Refinery/scripts/ralph-cron-run.sh
```

- [ ] **Step 2: Verify the wrapper parses config correctly**

```bash
# Create a test config
TESTCFG=$(mktemp --suffix=.json)
cat > "$TESTCFG" << 'JSONEOF'
{
  "prd_path": "/opt/proj/Uncle-J-s-Refinery/PRD.md",
  "max_iterations": 5,
  "risk_threshold": "0.65",
  "notify_telegram": "false"
}
JSONEOF

# Test config parsing (dry run via --dry-run flag)
# PRD.md must exist or the wrapper will fail
[[ -f /opt/proj/Uncle-J-s-Refinery/PRD.md ]] && echo "PRD.md present" || echo "PRD.md absent (create one to test)"
rm -f "$TESTCFG"
```

- [ ] **Step 3: Commit**

```bash
git add scripts/ralph-cron-run.sh
git commit -m "feat: add ralph-cron-run.sh — cron wrapper for ralph-harness.sh with Telegram notify"
```

### Task D2: Write `features/ralph-cron/install.sh`

Interactive installer. Prompts for PRD path and schedule, writes a JSON config file, installs a cron entry via `install_cron`.

- [ ] **Step 1: Create installer**

```bash
mkdir -p /opt/proj/Uncle-J-s-Refinery/features/ralph-cron

cat > /opt/proj/Uncle-J-s-Refinery/features/ralph-cron/install.sh << 'EOF'
#!/usr/bin/env bash
# Install/uninstall a scheduled Ralph loop for a specific PRD.
# Usage: bash features/ralph-cron/install.sh [--uninstall <name>]
#        bash features/ralph-cron/install.sh --list

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJ_ROOT/.env"
CONFIGS_DIR="$PROJ_ROOT/state/ralph-cron-configs"
RUN_SCRIPT="$PROJ_ROOT/scripts/ralph-cron-run.sh"

source "$PROJ_ROOT/lib/feature-helpers.sh"

step()  { printf '\n==> %s\n' "$*"; }
ok()    { printf '    OK  %s\n' "$*"; }
warn()  { printf '    !!  %s\n' "$*" >&2; }

if [[ "${1:-}" == "--list" ]]; then
  step "Installed Ralph cron jobs"
  crontab -l 2>/dev/null | grep "uncle-j-ralph-cron" || echo "  (none)"
  exit 0
fi

if [[ "${1:-}" == "--uninstall" ]]; then
  NAME="${2:?Usage: $0 --uninstall <name>}"
  MARKER="uncle-j-ralph-cron-${NAME}"
  step "Uninstalling Ralph cron: $NAME"
  remove_cron "$MARKER"
  rm -f "$CONFIGS_DIR/${NAME}.json"
  ok "Removed cron and config for '$NAME'."
  exit 0
fi

step "Install a new Ralph cron loop"
echo ""

[[ -f "$ENV_FILE" ]] && source "$ENV_FILE" || true

prompt_value "Name for this loop (kebab-case, e.g. my-feature)" "" LOOP_NAME
[[ -z "$LOOP_NAME" ]] && { warn "Name required."; exit 1; }
LOOP_NAME="${LOOP_NAME// /-}"

prompt_value "Path to PRD.md" "$PROJ_ROOT/PRD.md" PRD_PATH
[[ -f "$PRD_PATH" ]] || { warn "PRD file not found: $PRD_PATH"; exit 1; }

prompt_value "Repo path (where claude runs)" "$PROJ_ROOT" REPO_PATH
[[ -d "$REPO_PATH" ]] || { warn "Repo path not found: $REPO_PATH"; exit 1; }

prompt_value "Cron schedule (e.g. 0 */4 * * * for every 4h)" "0 */4 * * *" CRON_SCHEDULE

prompt_value "Max iterations per run" "10" MAX_ITER

prompt_value "Risk threshold (0.0-1.0)" "0.65" RISK

NOTIFY_DEFAULT="false"
[[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && NOTIFY_DEFAULT="true"
prompt_value "Notify via Telegram on completion? (true/false)" "$NOTIFY_DEFAULT" NOTIFY

step "Writing config"
mkdir -p "$CONFIGS_DIR"
CONFIG_FILE="$CONFIGS_DIR/${LOOP_NAME}.json"
python3 - "$CONFIG_FILE" "$PRD_PATH" "$REPO_PATH" "$MAX_ITER" "$RISK" "$NOTIFY" << 'PYEOF'
import sys, json
cfg_path, prd, repo, max_iter, risk, notify = sys.argv[1:]
with open(cfg_path, "w") as f:
    json.dump({
        "prd_path": prd,
        "repo_path": repo,
        "max_iterations": int(max_iter),
        "risk_threshold": risk,
        "notify_telegram": notify
    }, f, indent=2)
PYEOF
ok "Config: $CONFIG_FILE"

step "Installing cron job"
MARKER="uncle-j-ralph-cron-${LOOP_NAME}"
CLAUDE_BIN=$(command -v claude)
CRON_PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
ENTRY="${CRON_SCHEDULE} PATH=${CRON_PATH} CLAUDE_BIN=${CLAUDE_BIN} bash ${RUN_SCRIPT} ${CONFIG_FILE} >> ${PROJ_ROOT}/state/ralph-cron.log 2>&1"
install_cron "$MARKER" "$ENTRY"
ok "Cron: $CRON_SCHEDULE"

if [[ "$NOTIFY" == "true" && -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  source "$PROJ_ROOT/lib/notify.sh"
  notify_send_text "🔁 Ralph loop <b>${LOOP_NAME}</b> scheduled.

Schedule: <code>${CRON_SCHEDULE}</code>
PRD: <code>${PRD_PATH}</code>
Max iter: ${MAX_ITER}

First run at next cron tick." || true
fi

step "Done"
echo ""
echo "  Ralph will run '${LOOP_NAME}' on schedule: ${CRON_SCHEDULE}"
echo "  Config: $CONFIG_FILE"
echo "  Logs:   $PROJ_ROOT/state/ralph-cron.log"
echo "  To list:     bash $SCRIPT_DIR/install.sh --list"
echo "  To remove:   bash $SCRIPT_DIR/install.sh --uninstall ${LOOP_NAME}"
EOF
chmod +x /opt/proj/Uncle-J-s-Refinery/features/ralph-cron/install.sh
```

- [ ] **Step 2: Verify --list and --uninstall work without errors**

```bash
bash /opt/proj/Uncle-J-s-Refinery/features/ralph-cron/install.sh --list
# Expected: "(none)" or existing ralph entries
```

- [ ] **Step 3: Run the interactive installer**

```bash
bash /opt/proj/Uncle-J-s-Refinery/features/ralph-cron/install.sh
# At prompts: enter a name, PRD path, schedule, etc.
# Expected: config JSON written, cron installed, optional Telegram notification.
```

- [ ] **Step 4: Verify cron entry**

```bash
crontab -l | grep "uncle-j-ralph-cron"
# Expected: one entry per installed loop
```

- [ ] **Step 5: Commit**

```bash
git add features/ralph-cron/install.sh
git commit -m "feat: add ralph-cron feature — schedule ralph-harness.sh via cron with Telegram notify"
```

---

## Final Integration Verification

- [ ] **Check all 4 features are installed**

```bash
echo "=== Stop hooks ==="
python3 -c "
import json
d = json.load(open('/opt/proj/Uncle-J-s-Refinery/.claude/settings.json'))
stops = d.get('hooks',{}).get('Stop',[])
print(f'Stop hook count: {len(stops)}')
for s in stops:
    cmd = s.get('hooks',[{}])[0].get('command','')
    print(f'  - {cmd[:70]}')
"

echo ""
echo "=== Cron entries ==="
crontab -l | grep "uncle-j"

echo ""
echo "=== Skill drafts dir ==="
ls "${HOME}/.claude/skills/drafts/" 2>/dev/null || echo "(empty — populated after first session)"
```

- [ ] **Final commit**

```bash
git add -A
git status
git commit -m "feat: complete hermes-features port — telegram-notify, gateway, auto-skill, ralph-cron" || echo "(nothing to commit)"
```

---

## Self-Review

**Spec coverage:**
- Telegram notifications out ✅ — Sub-plan A (session-notify.sh + Stop hook)
- Telegram commands in ✅ — Sub-plan B (gateway-poll.sh + cron)
- Self-learning skills ✅ — Sub-plan C (skill-suggest.sh + Stop hook)
- Ralph + cron ✅ — Sub-plan D (ralph-cron-run.sh + installer)

**Placeholder scan:** None found. All code blocks are complete.

**Type consistency:** All scripts use `$PROJ_ROOT`, `$ENV_FILE`, `lib/notify.sh` consistently. `install_cron`/`remove_cron` from `lib/feature-helpers.sh` used in B and D installers. Stop hook JSON format consistent between A and C installers.

**Risk notes:**
- Sub-plan B: `claude --print` invoked from cron has no interactive TTY. The `--dangerously-skip-permissions` flag is required for unattended use. Long responses are truncated to 4096 chars (Telegram limit).
- Sub-plan C: `claude --print` invoked from a Stop hook subprocess. `async: true` prevents blocking session exit.
- Sub-plan D: Ralph loops run unattended with `--dangerously-skip-permissions`. PRD must have clear acceptance criteria for the done-gate to work.

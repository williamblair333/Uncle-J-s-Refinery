#!/usr/bin/env bash
# scripts/skill-suggest.sh — Claude Code Stop hook
# Reads the session transcript, calls claude --print to decide whether
# the session demonstrates a reusable skill, and auto-drafts a Markdown
# skill file if so.
# Invoked by Claude Code with a JSON payload on stdin.

set -euo pipefail
trap 'exit 0' ERR

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

# Exit early if transcript is missing
[[ -z "$TRANSCRIPT_PATH" ]] && exit 0
[[ -f "$TRANSCRIPT_PATH" ]] || exit 0

# Extract ALL assistant messages from the transcript, concatenated with ---
# Truncate total to 6000 chars to stay within claude --print limits
TRANSCRIPT_TEXT="$(python3 -c "
import sys, json

path = sys.argv[1]
messages = []

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
            # Transcripts use type='assistant' at top level; text is under message.content
            if obj.get('type') != 'assistant':
                continue
            content = obj.get('message', {}).get('content', obj.get('content', ''))
            text = ''
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        parts.append(block.get('text', ''))
                text = ' '.join(parts)
            if text.strip():
                messages.append(text.strip())
except Exception:
    pass

combined = '\n---\n'.join(messages)
print(combined[:6000], end='')
" "$TRANSCRIPT_PATH")"

# Nothing to analyze if transcript yielded no assistant messages
[[ -z "$TRANSCRIPT_TEXT" ]] && exit 0

# Write the analysis prompt to a temp file to avoid quoting issues
TMPFILE="$(mktemp /tmp/skill-suggest-prompt.XXXXXX)"
trap 'rm -f "$TMPFILE"' EXIT

cat > "$TMPFILE" <<'PROMPT_EOF'
You are reviewing a Claude Code session transcript to decide whether the session demonstrated a meaningful, reusable workflow worth capturing as a skill file.

Analyze the assistant messages below and decide:
- YES if the session shows a clear, repeatable workflow or technique that a user could invoke again (e.g. a debugging strategy, a code generation pattern, a data analysis approach, a refactoring technique, a multi-step automation).
- NO if the session was routine Q&A, trivial edits, one-off lookups, or contained nothing generalizable.

Rules for your response:
1. First line MUST be exactly one of: SKILL_DRAFT: YES   or   SKILL_DRAFT: NO
   (No backticks, no code fences, no markdown formatting on this line — plain text only.)
2. If YES, lines 2 onwards are the complete Markdown skill file content (including YAML frontmatter).
3. If NO, output nothing after the first line.
4. The skill draft must be under 200 lines total.
5. Only capture what was actually demonstrated — do not invent capabilities.
6. The skill file frontmatter must include `name` and `description` fields.
7. The skill body should explain when to use the skill and provide the key steps or commands demonstrated.

--- BEGIN TRANSCRIPT ---
PROMPT_EOF

printf '%s\n' "$TRANSCRIPT_TEXT" >> "$TMPFILE"
printf '\n--- END TRANSCRIPT ---\n' >> "$TMPFILE"

# Call claude --print to analyze the transcript
CLAUDE_OUTPUT="$(claude --dangerously-skip-permissions -p "@$TMPFILE" 2>/dev/null)" || true

# Parse: strip markdown fences, find SKILL_DRAFT line
CLEAN_OUTPUT="$(printf '%s' "$CLAUDE_OUTPUT" | grep -v '^```')"
FIRST_LINE="$(printf '%s' "$CLEAN_OUTPUT" | grep -m1 '^SKILL_DRAFT:' || true)"
if [[ "$FIRST_LINE" != "SKILL_DRAFT: YES" ]]; then
  exit 0
fi

# Extract skill markdown — everything after the SKILL_DRAFT line
SKILL_MARKDOWN="$(printf '%s' "$CLEAN_OUTPUT" | awk '/^SKILL_DRAFT:/{found=1; next} found{print}')"
[[ -z "$SKILL_MARKDOWN" ]] && exit 0

# Write draft to ~/.claude/skills/drafts/
DRAFTS_DIR="$HOME/.claude/skills/drafts"
mkdir -p "$DRAFTS_DIR"
DRAFT_FILE="$DRAFTS_DIR/${SHORT_ID}-skill-draft.md"
printf '%s\n' "$SKILL_MARKDOWN" > "$DRAFT_FILE"

# Send Telegram notification
PREVIEW="$(printf '%s' "$SKILL_MARKDOWN" | head -c 300)"
MSG="$(printf '📝 Skill draft auto-generated for session <code>%s</code>.\n\n<b>File:</b> <code>%s</code>\n\n<b>Preview:</b>\n<pre>%s</pre>' \
  "$SHORT_ID" "$DRAFT_FILE" "$PREVIEW")"

notify_send_text "$MSG" || true

exit 0

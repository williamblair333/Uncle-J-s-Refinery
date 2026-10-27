#!/usr/bin/env bash
# PreToolUse hook for self-work budget — nudges Claude sessions to delegate
# to agy / Heretic / local models instead of doing all work themselves.
# FAIL OPEN: no jq, unparseable stdin, unwritable state -> allow.
set -uo pipefail

command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat) || exit 0
[ -n "$INPUT" ] || exit 0

# Parse tool_name, session_id, cwd, and whether a Bash command contains CLAUDE-ONLY: in one jq call
readarray -t PARSED < <(
  printf '%s' "$INPUT" | jq -r '
    (.tool_name // ""),
    (.session_id // ""),
    (.cwd // ""),
    (if (.tool_name == "Bash" and ((.tool_input.command // "") | contains("CLAUDE-ONLY:"))) then "1" else "0" end)
  ' 2>/dev/null
) || exit 0

[ "${#PARSED[@]}" -ge 4 ] || exit 0

TOOL_NAME="${PARSED[0]}"
SESSION_ID="${PARSED[1]}"
CWD="${PARSED[2]}"
HAS_CLAUDE_ONLY="${PARSED[3]}"

# session_id and tool_name are required to track state; fail open if missing
[ -n "$TOOL_NAME" ] && [ -n "$SESSION_ID" ] || exit 0

# Clean session_id for use as a filename
SAFE_SESSION=$(basename "$SESSION_ID")
[ -n "$SAFE_SESSION" ] || exit 0

SELF_WORK_DIR="${SELF_WORK_DIR:-${HOME:-/nonexistent}/.claude/state/self-work}"
COUNT_FILE="$SELF_WORK_DIR/$SAFE_SESSION.count"
STATE_LOG="${SELF_WORK_LOG:-${HOME:-/nonexistent}/.claude/state/self-work.jsonl}"
BUDGET="${SELF_WORK_BUDGET:-20}"
[[ "$BUDGET" =~ ^[0-9]+$ ]] || BUDGET=20
MAX_LOG_BYTES="${SELF_WORK_LOG_MAX_BYTES:-5242880}"
[[ "$MAX_LOG_BYTES" =~ ^[0-9]+$ ]] || MAX_LOG_BYTES=5242880
PRUNE_DAYS="${SELF_WORK_PRUNE_DAYS:-7}"
[[ "$PRUNE_DAYS" =~ ^[0-9]+$ ]] || PRUNE_DAYS=7

log_decision() {  # $1 decision (allow/deny/delegate) — logging must never fail the hook
  local decision="$1"
  local ts sess proj clean_tool clean_proj log_size
  {
    if [ -d "$SELF_WORK_DIR" ]; then
      find "$SELF_WORK_DIR" -maxdepth 1 -name "*.count" -type f -mtime +"$PRUNE_DAYS" -delete 2>/dev/null || true
    fi
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date +%Y-%m-%dT%H:%M:%SZ)
    sess="${SESSION_ID:0:8}"
    proj=""
    if [ -n "$CWD" ]; then
      proj=$(basename "$CWD" 2>/dev/null || echo "")
      case "$proj" in
        parley-seat-*) proj="parley-seat" ;;
      esac
    fi
    clean_tool=${TOOL_NAME//\\/\\\\}
    clean_tool=${clean_tool//\"/\\\"}
    clean_proj=${proj//\\/\\\\}
    clean_proj=${clean_proj//\"/\\\"}
    mkdir -p "$(dirname "$STATE_LOG")" && {
      if [ -f "$STATE_LOG" ]; then
        log_size=$(wc -c < "$STATE_LOG" 2>/dev/null || echo 0)
        log_size=${log_size//[!0-9]/}
        if [ -n "$log_size" ] && [ "$log_size" -gt "$MAX_LOG_BYTES" ]; then
          mv -f "$STATE_LOG" "${STATE_LOG}.1" 2>/dev/null || true
        fi
      fi
      printf '{"ts":"%s","decision":"%s","tool":"%s","project":"%s","session":"%s"}\n' \
        "$ts" "$decision" "$clean_tool" "$clean_proj" "$sess" >> "$STATE_LOG"
    }
  } 2>/dev/null || true
}

# 1. Delegation tool: reset counter to 0, log delegate, allow
case "$TOOL_NAME" in
  mcp__delegate__ask_agy|mcp__delegate__ask_heretic|mcp__delegate__ask_openai|\
  mcp__ask_local__ask_local|mcp__ask_local__summarize_local|mcp__ask_local__extract_local)
    if ! { mkdir -p "$SELF_WORK_DIR" && echo 0 > "$COUNT_FILE"; } 2>/dev/null; then
      log_decision allow
      exit 0
    fi
    log_decision delegate
    exit 0
    ;;
esac

# 2. Bash command containing CLAUDE-ONLY: allowed without counting
if [ "$TOOL_NAME" = "Bash" ] && [ "$HAS_CLAUDE_ONLY" = "1" ]; then
  log_decision allow
  exit 0
fi

# 3. Self-work tools: increment count. When count exceeds BUDGET: deny once, reset to 0
case "$TOOL_NAME" in
  Read|Edit|Write|MultiEdit|NotebookEdit|Bash|Grep|Glob)
    current=0
    if [ -f "$COUNT_FILE" ]; then
      raw_count=$(cat "$COUNT_FILE" 2>/dev/null || echo 0)
      if [[ "$raw_count" =~ ^[0-9]+$ ]]; then
        current=$raw_count
      fi
    fi
    count=$((current + 1))
    if [ "$count" -gt "$BUDGET" ]; then
      if ! { mkdir -p "$SELF_WORK_DIR" && echo 0 > "$COUNT_FILE"; } 2>/dev/null; then
        log_decision allow
        exit 0
      fi
      log_decision deny
      printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Self-work budget: %d tool calls without delegating. Hand the next bounded piece to ask_agy(task=light|code|hard|review) or ask_heretic/ask_local; keep only review and edits mid-conversation. Retry to continue if this genuinely needs Claude."}}\n' "$count"
      exit 0
    fi

    if ! { mkdir -p "$SELF_WORK_DIR" && echo "$count" > "$COUNT_FILE"; } 2>/dev/null; then
      log_decision allow
      exit 0
    fi
    log_decision allow
    exit 0
    ;;
esac

# 4. Everything else: allow, no count
log_decision allow
exit 0

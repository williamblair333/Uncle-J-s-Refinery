#!/usr/bin/env bash
# PreToolUse guard — blocks grep -r on source dirs; routes to jcodemunch search_text.
set -uo pipefail

LOG="/opt/proj/Uncle-J-s-Refinery/state/hook-blocks.log"

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo "unknown")

log_entry() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG" 2>/dev/null || true; }

[[ -z "${CMD:-}" ]] && exit 0

# Detect recursive grep on source (not log/state/tmp targets)
is_source_grep() {
  echo "$CMD" | grep -qE 'grep\s+(-[a-zA-Z]*r[a-zA-Z]*|--recursive)\b' || return 1
  # Allow: log/state/tmp targets are fine
  echo "$CMD" | grep -qE '(/tmp/|/var/log/|state/|\.log\b|hook-blocks|/proc/)' && return 1
  return 0
}

is_source_grep || exit 0

log_entry "BLOCKED grep-guard cmd=$(echo "$CMD" | head -c 120) session=$SESSION_ID"

REASON="grep -r on source is blocked. Use jcodemunch search_text instead:

  mcp__jcodemunch__search_text(query=\"your pattern\", repo_id=<repo_id>)

Why: grep dumps raw file contents into context; search_text returns structured
file:line results without bloating context. Regex is supported.

To find your repo_id first:
  mcp__jcodemunch__list_repos()

Logged to state/hook-blocks.log"

jq -n --arg r "$REASON" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": $r
  }
}'

#!/usr/bin/env bash
# PreToolUse guard — blocks Edit/Write on surface-list files until pre-mortem clears.
# Bypass: invoke /pre-mortem skill — the skill writes PRE-MORTEM-COMPLETE to the token
# file as its final step. Direct `touch` of the token is blocked by Bash PreToolUse hook.
# Token path: /tmp/premortem-cleared-SESSION_ID (non-empty content required).
set -uo pipefail

LOG="/opt/proj/Uncle-J-s-Refinery/state/hook-blocks.log"
BYPASS_PREFIX="/tmp/premortem-cleared"

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo "unknown")
BYPASS_FILE="${BYPASS_PREFIX}-${SESSION_ID}"

log_entry() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG" 2>/dev/null || true; }

[[ -z "${FILE_PATH:-}" ]] && exit 0

is_surface() {
  local f="$1" b
  b="$(basename "$f")"
  [[ "$f" == *.sh ]]            && return 0
  [[ "$f" == *.py ]]            && return 0
  [[ "$f" == *.toml ]]          && return 0
  [[ "$f" == *.yml ]]           && return 0
  [[ "$f" == *.yaml ]]          && return 0
  [[ "$b" == Dockerfile* ]]     && return 0
  [[ "$b" == settings.json ]]   && return 0
  [[ "$b" == CLAUDE.md ]]       && return 0
  [[ "$f" == *"/scripts/"* ]]   && return 0
  [[ "$f" == *"/hooks/"* ]]     && return 0
  [[ "$f" == *"/features/"* ]]  && return 0
  [[ "$b" == install*.sh ]]     && return 0
  [[ "$b" == *.cfg ]]           && return 0
  [[ "$b" == *.ini ]]           && return 0
  [[ "$b" == crontab* ]]        && return 0
  return 1
}

is_surface "$FILE_PATH" || exit 0

if [[ -f "$BYPASS_FILE" ]] && [[ -s "$BYPASS_FILE" ]]; then
  rm -f "$BYPASS_FILE"
  log_entry "ALLOWED edit-surface-guard file=$FILE_PATH session=$SESSION_ID"
  exit 0
fi

log_entry "BLOCKED edit-surface-guard file=$FILE_PATH session=$SESSION_ID"

REASON="PRE-MORTEM REQUIRED before editing: $(basename "$FILE_PATH")

Surface matched: $FILE_PATH

Steps:
  1. Invoke /pre-mortem skill — it will write the clearance token as its final step.
  2. Retry the edit.

Token path (written by the skill, not manually): $BYPASS_FILE
WARNING: Direct token creation (touch, echo, Write) is blocked by Bash PreToolUse hook.

Logged to state/hook-blocks.log for weekly review."

jq -n --arg r "$REASON" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": $r
  }
}'

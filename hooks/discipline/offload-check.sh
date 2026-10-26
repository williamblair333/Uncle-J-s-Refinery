#!/usr/bin/env bash
# PreToolUse hook for the Agent tool — makes offloading the default, not a thing to remember.
# A Claude subagent spends Claude tokens. Unless the prompt carries a line
#   CLAUDE-ONLY: <why this needs Claude>
# (or the subagent type is one of the built-ins that only Claude can serve), deny and
# point at ask_agy (task=light|code|hard|review) / ask_local / ask_heretic instead.
# Every decision appends {ts, decision, subagent_type} to ~/.claude/state/offload-check.jsonl
# (never fails the hook), so the log measures how often Claude spawned vs was told to offload.
# FAIL OPEN: no jq, unparseable stdin, anything unexpected → allow. A broken advisory hook
# must never lock Claude out of subagents.
set -uo pipefail

STATE_LOG="${HOME:-/nonexistent}/.claude/state/offload-check.jsonl"

log_decision() {  # $1 decision, $2 subagent_type — logging must never fail the hook
  {
    mkdir -p "$(dirname "$STATE_LOG")" &&
      jq -cn --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg d "$1" --arg s "$2" \
        '{ts: $ts, decision: $d, subagent_type: $s}' >> "$STATE_LOG"
  } 2>/dev/null || true
}

command -v jq >/dev/null 2>&1 || exit 0

INPUT=$(cat) || exit 0
SUBAGENT=$(printf '%s' "$INPUT" | jq -er '.tool_input.subagent_type // ""' 2>/dev/null) || exit 0
PROMPT=$(printf '%s' "$INPUT" | jq -er '.tool_input.prompt // ""' 2>/dev/null) || exit 0

case "$SUBAGENT" in
  fork|claude-code-guide|statusline-setup)
    log_decision allow "$SUBAGENT"
    exit 0
    ;;
esac

if printf '%s\n' "$PROMPT" | grep -Eq '^CLAUDE-ONLY:[[:space:]]*[^[:space:]]'; then
  log_decision allow "$SUBAGENT"
  exit 0
fi

log_decision deny "$SUBAGENT"
printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Offload check: send this to ask_agy (task=light|code|hard|review) or ask_local/ask_heretic. If it truly needs Claude, add a line '"'"'CLAUDE-ONLY: <why>'"'"' to the prompt."}}'
exit 0

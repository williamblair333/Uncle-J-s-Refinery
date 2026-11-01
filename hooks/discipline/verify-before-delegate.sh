#!/usr/bin/env bash
# PreToolUse: the first delegation in a session waits until the verifiable-task skill has run.
#
# CLAUDE.md says "always use the verifiable-task skill" before delegating, but five mtw2 sessions
# (2026-10-30..11-01) called it 0 times while delegating to agy and subagents. Optional skills
# don't run unless something makes them. This denies the first delegation (ask_agy, ask_heretic,
# ask_openai, ask_local, Agent) in a session whose transcript has no verifiable-task Skill call,
# once: a retry goes through, so a session that genuinely can't call skills is never stuck.
#
# Exempt: subagents (agent_id in the input), read-only Agent types (Explore, claude-code-guide,
# statusline-setup). FAIL OPEN: no jq, bad input, no transcript, unwritable state -> allow.
set -uo pipefail
command -v jq >/dev/null 2>&1 || exit 0
INPUT=$(cat) || exit 0
[ -n "$INPUT" ] || exit 0

readarray -t F < <(printf '%s' "$INPUT" | jq -r '
  (.tool_name // ""), (.session_id // ""), (.transcript_path // ""),
  (.agent_id // ""), (.tool_input.subagent_type // "")' 2>/dev/null) || exit 0
[ "${#F[@]}" -ge 5 ] || exit 0
TOOL="${F[0]}"; SESSION="${F[1]}"; TRANSCRIPT="${F[2]}"; AGENT_ID="${F[3]}"; SUBTYPE="${F[4]}"

case "$TOOL" in
  mcp__delegate__ask_agy|mcp__delegate__ask_heretic|mcp__delegate__ask_openai|\
  mcp__ask_local__ask_local|mcp__ask_local__summarize_local|mcp__ask_local__extract_local) ;;
  Agent|Task)
    case "$SUBTYPE" in Explore|claude-code-guide|statusline-setup) exit 0 ;; esac ;;
  *) exit 0 ;;
esac
[ -z "$AGENT_ID" ] || exit 0
[ -n "$SESSION" ] && [ -f "$TRANSCRIPT" ] || exit 0

grep -qE '"skill" *: *"verifiable-task"' "$TRANSCRIPT" 2>/dev/null && exit 0

STATE_DIR="${VERIFY_GATE_DIR:-${HOME:-/nonexistent}/.claude/state/verify-gate}"
MARK="$STATE_DIR/$(basename "$SESSION").denied"
[ -f "$MARK" ] && exit 0
{ mkdir -p "$STATE_DIR" && : > "$MARK"; } 2>/dev/null || exit 0
find "$STATE_DIR" -maxdepth 1 -name '*.denied' -mtime +7 -delete 2>/dev/null || true
printf '{"ts":"%s","tool":"%s","session":"%s"}\n' "$(date -u +%FT%TZ)" "$TOOL" "${SESSION:0:8}" \
  >> "$STATE_DIR/denies.jsonl" 2>/dev/null || true

printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Before the first delegation of this session, invoke the verifiable-task skill with the Skill tool: write the check you will run on what comes back, then retry this call. (One-time per session; a retry goes through.)"}}'
exit 0

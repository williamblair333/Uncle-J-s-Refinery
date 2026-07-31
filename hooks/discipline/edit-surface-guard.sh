#!/usr/bin/env bash
# PreToolUse guard — blocks Edit/Write on surface-list files until pre-mortem clears.
# Token: /tmp/premortem-cleared-SESSION_ID
#   Format: JSON {"ts": <epoch>, "status": "PRE-MORTEM-COMPLETE"}
#   Written by: ~/.claude/hooks/pre-mortem-guard/write-clearance-token.sh (skill only)
#   Expiry: 2h session-scoped — one pre-mortem covers all related edits in the session
# FAIL CLOSED: parse errors → deny (never fall back to "unknown")
set -uo pipefail

# See grep-guard.sh: projects root is /opt/proj on Linux, /c/opt/proj under MSYS.
_PROJ_ROOT="${UNCLE_J_PROJ_ROOT:-}"
if [ -z "$_PROJ_ROOT" ]; then
  for _cand in /opt/proj /c/opt/proj; do
    [ -d "$_cand" ] && { _PROJ_ROOT="$_cand"; break; }
  done
fi
LOG="${_PROJ_ROOT:-/opt/proj}/Uncle-J-s-Refinery/state/hook-blocks.log"
BYPASS_PREFIX="/tmp/premortem-cleared"
TOKEN_MAX_AGE=7200

# This guard is documented FAIL CLOSED, but every deny it emits is produced by
# `jq -n`. With jq absent the deny prints nothing, Claude Code sees an empty
# decision, and the edit proceeds — fail closed inverts to fail open. Refuse to
# run rather than pretend to guard.
if ! command -v jq >/dev/null 2>&1; then
  echo "edit-surface-guard: jq not found on PATH — cannot emit a decision" >&2
  exit 1
fi

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || echo "")
BYPASS_FILE="${BYPASS_PREFIX}-${SESSION_ID}"

# python3 below is a Windows interpreter under Git Bash and cannot open an MSYS
# path such as /tmp/premortem-cleared-... — json.load then raises, token_valid()
# returns 1, and the guard denies every surface edit with no way to clear it.
# Hand the interpreter a native path. cygpath -m yields C:/... (forward slashes),
# which is safe to embed in the Python string literals below; -w would emit
# backslashes and break them.
BYPASS_FILE_PY="$BYPASS_FILE"
if command -v cygpath >/dev/null 2>&1; then
  BYPASS_FILE_PY="$(cygpath -m "$BYPASS_FILE" 2>/dev/null || printf '%s' "$BYPASS_FILE")"
fi

log_entry() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG" 2>/dev/null || true; }

[[ -z "${FILE_PATH:-}" ]] && exit 0

# FAIL CLOSED: deny if session_id is unparseable
if [[ -z "${SESSION_ID:-}" ]]; then
  log_entry "ERROR session_id parse failed for edit of $FILE_PATH — denying (fail closed)"
  jq -n '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Guard error: could not determine session_id — denying to fail closed."}}'
  exit 0
fi

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

# Block Write/Edit tool directly to any token path (prevents token forgery via Write tool)
if [[ "$FILE_PATH" == "${BYPASS_PREFIX}-"* ]]; then
  log_entry "BLOCKED token-path-write file=$FILE_PATH session=$SESSION_ID"
  jq -n '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"BLOCKED: Direct write to pre-mortem clearance token path.\nTokens must be created by write-clearance-token.sh (called by the /pre-mortem skill only)."}}'
  exit 0
fi

# Validate token: must be a regular file (not symlink), JSON {ts, status}, correct status, not expired.
# FAIL CLOSED: any parse error or unexpected condition → deny.
token_valid() {
  [[ -f "$BYPASS_FILE" ]] || return 1
  [[ -s "$BYPASS_FILE" ]] || return 1
  # Block symlink bypass: token must be a real file, not a symlink
  if [[ -L "$BYPASS_FILE" ]]; then
    log_entry "BLOCKED symlink-at-token-path file=$BYPASS_FILE session=$SESSION_ID"
    return 1
  fi
  if ! command -v python3 &>/dev/null; then
    log_entry "BLOCKED python3-unavailable — cannot validate JSON token (fail closed)"
    return 1
  fi
  local ts status now
  ts=$(python3 -c "import json; d=json.load(open('$BYPASS_FILE_PY')); print(d['ts'])" 2>/dev/null) || {
    log_entry "BLOCKED token-parse-failed file=$BYPASS_FILE — denying (fail closed)"
    return 1
  }
  status=$(python3 -c "import json; d=json.load(open('$BYPASS_FILE_PY')); print(d['status'])" 2>/dev/null) || return 1
  [[ "$status" == "PRE-MORTEM-COMPLETE" ]] || return 1
  now=$(date +%s)
  (( now - ts <= TOKEN_MAX_AGE )) || { rm -f "$BYPASS_FILE"; return 1; }
  return 0
}

if token_valid; then
  log_entry "ALLOWED edit-surface-guard file=$FILE_PATH session=$SESSION_ID"
  exit 0
fi

log_entry "BLOCKED edit-surface-guard file=$FILE_PATH session=$SESSION_ID"

REASON="PRE-MORTEM REQUIRED before editing: $(basename "$FILE_PATH")

Surface matched: $FILE_PATH

Steps:
  1. Invoke /pre-mortem skill — it calls write-clearance-token.sh as its final step.
  2. Retry the edit. Token is session-scoped (valid 2h) — one pre-mortem covers all related edits.

Token path (written by the skill): $BYPASS_FILE
WARNING: ALL direct token creation is blocked — touch, printf, echo, tee, cat, cp, python3,
  node, perl, dd, Write tool, > redirect. Only the pre-mortem skill may create this token.

Token format: JSON {\"ts\": <epoch>, \"status\": \"PRE-MORTEM-COMPLETE\"} — expires 2h.

Logged to state/hook-blocks.log for weekly review."

jq -n --arg r "$REASON" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": $r
  }
}'

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

# >>> hook_log_append — keep byte-identical in every hook that writes hook-blocks.log
#     (tests/test_hook_log.py compares the copies). Inline, not sourced: a hook whose
#     library went missing would fail open.
# One record per line, and text only: GNU grep treats a file holding a NUL byte or
# invalid UTF-8 as binary and prints nothing, so a reviewer reads silence as "no
# blocks". Every C0 control byte and DEL becomes a space; invalid UTF-8 (`head -c`
# cutting a multibyte character) is dropped. Past HOOK_LOG_MAX_BYTES the log is
# ARCHIVED to <log>.YYYYMMDD, never truncated: it is not reconstructible. The rename
# is atomic, a writer still holding the old file lands in the archive, `mv -n` never
# overwrites one, and a mkdir lock (broken after 60 s) keeps rotations single-file.
hook_log_append() {
  local log=$1 rec=$2 max=${HOOK_LOG_MAX_BYTES:-1048576} clean size lock arch
  rec=$(printf '%s' "$rec" | LC_ALL=C tr '\000-\037\177' ' ')
  if command -v iconv >/dev/null 2>&1; then
    clean=$(printf '%s' "$rec" | iconv -c -f UTF-8 -t UTF-8 2>/dev/null)
    [[ -n "$clean" ]] && rec=$clean
  fi
  if [[ -f "$log" ]]; then
    size=$(wc -c < "$log" 2>/dev/null | tr -dc '0-9')
    if [[ -n "$size" && "$size" -gt "$max" ]]; then
      lock="$log.rotate.lock"
      if [[ -d "$lock" && -n "$(find "$lock" -maxdepth 0 -mmin +1 2>/dev/null)" ]]; then
        rmdir "$lock" 2>/dev/null
      fi
      if mkdir "$lock" 2>/dev/null; then
        size=$(wc -c < "$log" 2>/dev/null | tr -dc '0-9')
        if [[ -n "$size" && "$size" -gt "$max" ]]; then
          arch="$log.$(date +%Y%m%d)"
          [[ -e "$arch" ]] && arch="$log.$(date +%Y%m%d-%H%M%S)-$$"
          [[ -e "$arch" ]] || mv -n -- "$log" "$arch" 2>/dev/null
        fi
        rmdir "$lock" 2>/dev/null
      fi
    fi
  fi
  printf '%s\n' "$rec" >> "$log" 2>/dev/null || true
}
# <<< hook_log_append

log_entry() { hook_log_append "$LOG" "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

[[ -z "${FILE_PATH:-}" ]] && exit 0

# FAIL CLOSED: deny if session_id is unparseable
if [[ -z "${SESSION_ID:-}" ]]; then
  log_entry "ERROR session_id parse failed for edit of $FILE_PATH — denying (fail closed)"
  jq -n '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Guard error: could not determine session_id — denying to fail closed."}}'
  exit 0
fi

# Surface list. Reviewed against state/hook-blocks.log 2026-10-23 (513 BLOCKED /
# 7532 ALLOWED since 2026-05-25):
#   * narrowed — a test module (tests/test_*.py, tests/*_test.py) is not a deploy
#     surface: 65 blocks, 13% of all blocks, every one a pre-mortem for a test edit.
#     conftest.py (runs at collection) and anything under hooks/, scripts/ or
#     features/ stay gated, so guard code is never exempted with its tests.
#   * widened — files that ARE the surface-list categories but matched no rule:
#     .mcp.json (PR #105: a committed project .mcp.json shadowed user scope and killed
#     all 5 stack servers), settings.local.json (hook + permission config, the
#     settings.json rule matched only that exact basename), justfile (every repo's
#     command entry point), *.service / *.timer (systemd: scheduled tasks).
#   * extensions compare case-insensitively (`deploy.SH` is still a script).
is_test_module() {
  local f="$1" b
  b="$(basename "$f")"
  case "$f" in */hooks/*|*/scripts/*|*/features/*) return 1 ;; esac
  case "$f" in */tests/*|*/test/*) ;; *) return 1 ;; esac
  [[ "$b" == test_*.py || "$b" == *_test.py ]]
}

is_surface() {
  local f="$1" b
  f="${f,,}"                    # lower-case: extension/name checks are case-blind
  b="$(basename "$f")"
  [[ "$b" == .mcp.json ]]       && return 0
  [[ "$b" == settings.local.json ]] && return 0
  [[ "$b" == justfile || "$b" == .justfile ]] && return 0
  [[ "$f" == *.service ]]       && return 0
  [[ "$f" == *.timer ]]         && return 0
  is_test_module "$1"           && return 1
  [[ "$f" == *.sh ]]            && return 0
  [[ "$f" == *.py ]]            && return 0
  [[ "$f" == *.toml ]]          && return 0
  [[ "$f" == *.yml ]]           && return 0
  [[ "$f" == *.yaml ]]          && return 0
  [[ "$b" == dockerfile* ]]     && return 0
  [[ "$b" == settings.json ]]   && return 0
  [[ "$b" == claude.md ]]       && return 0
  [[ "$f" == *"/scripts/"* ]]   && return 0
  [[ "$f" == *"/hooks/"* ]]     && return 0
  [[ "$f" == *"/features/"* ]]  && return 0
  [[ "$b" == install*.sh ]]     && return 0
  [[ "$b" == *.cfg ]]           && return 0
  [[ "$b" == *.ini ]]           && return 0
  [[ "$b" == crontab* ]]        && return 0
  return 1
}

# Judge the path as written AND where it lands: Edit/Write follow symlinks, so an
# innocuous-looking /tmp/notes.txt -> <repo>/hooks/x.sh edits the hook (red-team
# 2026-10-23: the literal-only check let that through with no pre-mortem).
_resolved=$(realpath -m -- "$FILE_PATH" 2>/dev/null) || _resolved=""
if ! is_surface "$FILE_PATH"; then
  [[ -n "$_resolved" ]] && is_surface "$_resolved" || exit 0
fi

# A scratch file under /tmp is not a surface edit (2026-10-16: 75 logged blocks of
# Write to $scratchpad/*.py). Exempt only what RESOLVES under /tmp — realpath -m
# folds `..` and follows existing symlinks — and never the token path, so the
# forgery check below still sees it. realpath missing → no exemption (fail closed).
# Same rule as the /tmp exemption in surface-write-guard.sh.
if [[ "$_resolved" == /tmp/?* && "$_resolved" != "${BYPASS_PREFIX}"* \
      && "$FILE_PATH" != "${BYPASS_PREFIX}"* ]]; then
  exit 0
fi

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
  # ts must be a plain epoch integer. It reached `(( ))` raw, and bash arithmetic
  # EVALUATES its operands: ts="now" made now-now=0 (a token that never expires),
  # ts="a[\$(cmd)]" ran a command, and a future ts gave a negative age that also
  # never expired (red-team 2026-10-23). Reject all three.
  [[ "$ts" =~ ^[0-9]{1,12}$ ]] || { log_entry "BLOCKED token-ts-invalid file=$BYPASS_FILE session=$SESSION_ID"; return 1; }
  now=$(date +%s)
  [[ "$now" =~ ^[0-9]+$ ]] || return 1
  (( 10#$ts <= now + 60 )) || { log_entry "BLOCKED token-ts-future file=$BYPASS_FILE session=$SESSION_ID"; return 1; }
  (( now - 10#$ts <= TOKEN_MAX_AGE )) || { rm -f "$BYPASS_FILE"; return 1; }
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

#!/usr/bin/env bash
# PreToolUse (Bash) guard: block running downloaded code unseen (curl … | bash, etc.).
#
# Replaces the inline settings.json regex (2026-11-04), which blocked
# `curl … | sha256sum` (no word boundary after `sh`) and ran across `;`/`&&`.
# The judging lives in pipe_to_shell_guard.py (tokenised, per command and pipeline
# stage; see its docstring). This wrapper exists so the guard never FAILS OPEN:
# Claude Code blocks only on exit 2, so a Python crash or a missing python3 would
# otherwise let everything through. Any outcome other than a clean 0 or 2 falls
# back to a word-bounded version of the old regex, run here in bash.
# Deployed by scripts/repoint-pipe-guard.sh; tests: tests/test_pipe_to_shell_guard.py.

DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
INPUT=$(cat)

MSG=$(printf '%s' "$INPUT" | python3 -I "$DIR/pipe_to_shell_guard.py" 2>&1 >/dev/null)
RC=$?
[[ $RC -eq 0 ]] && exit 0
if [[ $RC -ne 2 ]]; then
    FALLBACK='\b(curl|wget)\b[^;&|]*\|\s*(sudo\s+)?(\S*/)?(bash|sh|zsh|dash|ksh)\b|\b(bash|sh|zsh)\s+<\(\s*(curl|wget)\b|\b(bash|sh|zsh|dash|ksh|eval)\b[^;&|]*["'"'"'[:space:]]\$\(\s*(curl|wget)\b'
    printf '%s' "$INPUT" | grep -qE "$FALLBACK" || exit 0
    MSG="BLOCKED: Pipe-to-shell detected (regex fallback: the guard exited $RC). Download first, inspect, then execute."
fi

LOG="${PIPE_GUARD_LOG:-$DIR/../../state/hook-blocks.log}"
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

SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo unknown)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
hook_log_append "$LOG" "$(date '+%Y-%m-%d %H:%M:%S') BLOCKED pipe-to-shell-guard cmd=$(printf '%s' "${CMD:-?}" | tr '\n\r\t' ' ' | head -c 200) session=${SESSION_ID:-unknown}"
echo "$MSG" >&2
exit 2

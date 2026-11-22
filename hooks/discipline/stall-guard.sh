#!/usr/bin/env bash
# PreToolUse (Bash) stall guard: refuse waits that can hang without telling anyone.
# The judging lives in stall_guard.py (see its docstring for the rules). This wrapper fails
# OPEN: Claude Code blocks only on exit 2, and a behaviour guard that crashed must never
# lock every Bash call out of a session, so anything but a clean 2 passes.
# Wired by install-reliability.sh; tests: tests/test_stall_guard.py.

DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
INPUT=$(cat)

MSG=$(printf '%s' "$INPUT" | python3 -I "$DIR/stall_guard.py" 2>&1 >/dev/null)
RC=$?
# python itself exits 2 when it can't open the script: only the judge's own refusal blocks.
[[ $RC -eq 2 && $MSG == stall-guard:* ]] || exit 0

LOG="${STALL_GUARD_LOG:-$DIR/../../state/hook-blocks.log}"
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
hook_log_append "$LOG" "$(date '+%Y-%m-%d %H:%M:%S') BLOCKED stall-guard rule=$(printf '%s' "$MSG" | sed -E 's/^stall-guard: ([a-z-]+).*/\1/' | head -c 40) cmd=$(printf '%s' "${CMD:-?}" | tr '\n\r\t' ' ' | head -c 200) session=${SESSION_ID:-unknown}"
echo "$MSG" >&2
exit 2

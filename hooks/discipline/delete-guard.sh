#!/usr/bin/env bash
# PreToolUse (Bash) guard: block commands that delete data outside the repo or temp
# dirs (rm of ~ paths, virsh --remove-all-storage, git reset --hard, docker volume rm,
# mkfs, and `just` recipes or scripts that run those). See delete_guard.py.
#
# Added 2026-11-27 after `just vm-destroy` (virsh undefine --remove-all-storage)
# deleted the RHEL DVD ISO attached to a lab VM. Blocks with exit 2. A command
# prefixed DELETE_OK="<what; who approved>" passes, and the prefix is logged.
# Like pipe-to-shell-guard.sh, this wrapper never FAILS OPEN: anything other than
# a clean 0 or 2 from the judge falls back to a regex run here in bash.
# Wired by install-reliability.sh; tests: tests/test_delete_guard.py.

DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
INPUT=$(cat)
ERRF=$(mktemp 2>/dev/null || echo "/tmp/delete-guard.$$")

OUT=$(printf '%s' "$INPUT" | python3 -I "$DIR/delete_guard.py" 2>"$ERRF")
RC=$?
MSG=$(cat "$ERRF" 2>/dev/null)
rm -f -- "$ERRF"

if [[ $RC -ne 0 && $RC -ne 2 ]]; then
    # shellcheck disable=SC2016  # $HOME is matched literally, not expanded
    FALLBACK='--remove-all-storage|--wipe-storage|\bvol-delete\b|\bgit[[:space:]]+reset[[:space:]]+--hard\b|\bmkfs|\bwipefs\b|\brm[[:space:]]+(-[[:alnum:]]+[[:space:]]+)*(/|~|\$HOME)'
    CMD0=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || printf '%s' "$INPUT")
    if printf '%s' "$CMD0" | grep -qE -- "$FALLBACK" && ! printf '%s' "$CMD0" | grep -qE '(^|[[:space:];&|(])DELETE_OK=[^[:space:]]'; then
        MSG="BLOCKED (delete-guard, regex fallback: the judge exited $RC)."
        RC=2
        MSG="$MSG This deletes data outside the repo or temp dirs. List what it deletes, ask William for anything not recreatable, then prefix the command DELETE_OK=\"<what; who approved>\"."
    else
        exit 0
    fi
fi
[[ $RC -eq 0 && -z "$OUT" ]] && exit 0

LOG="${DELETE_GUARD_LOG:-$DIR/../../state/hook-blocks.log}"
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
SHORT=$(printf '%s' "${CMD:-?}" | tr '\n\r\t' ' ' | head -c 200)
NOW=$(date '+%Y-%m-%d %H:%M:%S')
while IFS= read -r line; do
    [[ -n "$line" ]] && hook_log_append "$LOG" "$NOW ALLOWED delete-guard ${line:0:300} cmd=$SHORT session=${SESSION_ID:-unknown}"
done <<< "$OUT"
[[ $RC -eq 0 ]] && exit 0

hook_log_append "$LOG" "$NOW BLOCKED delete-guard cmd=$SHORT session=${SESSION_ID:-unknown}"
echo "$MSG" >&2
exit 2

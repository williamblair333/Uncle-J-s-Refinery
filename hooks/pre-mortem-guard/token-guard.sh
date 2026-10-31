#!/usr/bin/env bash
# PreToolUse(Bash): blocks every direct way of creating a pre-mortem clearance token
# (/tmp/premortem-cleared-*). Only the pre-mortem skill's call to
# write-clearance-token.sh may write one. Also blocks `rm` of hook/guard scripts.
#
# Versioned here since 2026-10-31; it was a real file in ~/.claude for months (same
# story as surface-write-guard.sh) and install-reliability.sh now symlinks it.
# Changes from that copy, all pinned by tests/test_token_guard.py:
#   * Reads are not writes. `cat` left the write list (it writes only through a
#     redirect, which the redirect pattern catches) and python needs a write call.
#     About a dozen token reads (`cat <token>`, `ls x; cat y`, `json.load(open(t))`)
#     were blocked in state/hook-blocks.log 2026-06 to 2026-10.
#     Patterns still use `.*`, which spans `;`/`&&`/`|`: a segment-local match would
#     miss `touch ';' <token>` (the split can't see quotes). Spanning costs a false
#     hit only when a write tool and a token path share one command.
#   * The authorized writer is matched by file identity (realpath), not by the
#     /home/bill spelling, and only its own call is exempt: before, its presence
#     anywhere let the whole command through, `&& touch <token>` included.
#   * The log path honours UNCLE_J_PROJ_ROOT and goes through hook_log_append, so
#     tests and scripts/hook_bench.py replays log nowhere real.
set -uo pipefail

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || echo "")
[[ -z "$CMD" ]] && exit 0

TOKEN_PREFIX="/tmp/premortem-cleared"
TP=${TOKEN_PREFIX//\//\\/}
GUARD_DIR=$(dirname "$(realpath -- "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")")
AUTHORIZED=$(realpath -e -- "$GUARD_DIR/write-clearance-token.sh" 2>/dev/null || echo "")

PROJ_ROOTS="${UNCLE_J_PROJ_ROOT:+$UNCLE_J_PROJ_ROOT }/opt/proj /c/opt/proj"
LOG_ROOT=/opt/proj
for _cand in $PROJ_ROOTS; do
  [ -d "$_cand" ] && { LOG_ROOT="$_cand"; break; }
done
LOG="$LOG_ROOT/Uncle-J-s-Refinery/state/hook-blocks.log"

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

deny() {  # $1 = log tag, $2 = reason
  local sid
  sid=$(printf '%s' "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo "unknown")
  hook_log_append "$LOG" "$(date '+%Y-%m-%d %H:%M:%S') BLOCKED $1 cmd=$(printf '%s' "$CMD" | tr '\n\r\t' ' ' | head -c 200) session=$sid"
  jq -n --arg r "$2" '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":$r}}'
  exit 0
}

S='(^|[[:space:];|&(])'   # command start: line start or a separator

# rm of a hook/guard script disables enforcement.
GUARD_PATHS='(/hooks/|/discipline/|/pre-mortem-guard/|/scan-commit/|/scan-secrets/|/prompt-injection-defender/)'
if printf '%s\n' "$CMD" | grep -qE "${S}rm[[:space:]].*${GUARD_PATHS}"; then
  deny "guard-deletion-attempt" "BLOCKED: rm of hook/guard script detected.

Deleting enforcement scripts disables security controls. If you need to modify a hook, use the Edit tool (requires pre-mortem clearance)."
fi

# Exempt the authorized writer's own call(s): `bash <path> /tmp/premortem-cleared-…`
# where <path> resolves to the write-clearance-token.sh next to this guard. Only that
# call is cut out; the rest of the command is still scanned.
SCAN=$CMD
re="(^|[[:space:];|&(])bash[[:space:]]+([^[:space:];|&]+)[[:space:]]+${TOKEN_PREFIX}[^[:space:];|&]*"
while [[ -n "$AUTHORIZED" && "$SCAN" =~ $re ]]; do
  whole=${BASH_REMATCH[0]} script=${BASH_REMATCH[2]}
  [[ "$script" == "~/"* ]] && script="$HOME/${script#\~/}"
  [[ "$(realpath -e -- "$script" 2>/dev/null)" == "$AUTHORIZED" ]] || break
  SCAN=${SCAN/"$whole"/ }
done

WRITE=0
if printf '%s\n' "$SCAN" | grep -qE \
  "${S}(touch|tee|dd|install|rsync|cp|mv|ln|openssl|node|nodejs|perl|ruby)[[:space:]].*${TP}|\
[&]?>[>|]?[[:space:]]*[\"']?${TP}"; then
  WRITE=1
elif printf '%s\n' "$SCAN" | grep -E "${S}python3?[[:space:]].*${TP}" \
  | grep -qE "write|['\"][wax]b?\+?['\"]|touch|rename|replace|copy|move|symlink|link_to"; then
  WRITE=1
fi

if [[ $WRITE -eq 1 ]]; then
  deny "token-guard direct-token-write" "BLOCKED: Direct pre-mortem token creation.

Tokens MUST be created by the pre-mortem skill:
  1. Invoke /pre-mortem skill
  2. Complete the full analysis
  3. Skill calls write-clearance-token.sh as its LAST step

Blocked methods: touch, tee, cp, mv, ln, dd, install, rsync, python writes, node, perl, ruby, openssl, any > redirect.
Reading a token (cat, ls, python open()) is allowed.
Allowed writer: bash ~/.claude/hooks/pre-mortem-guard/write-clearance-token.sh <token-path>"
fi

exit 0

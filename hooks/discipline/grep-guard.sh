#!/usr/bin/env bash
# PreToolUse guard — routes SOURCE-CODE exploration to jcodemunch (token + accuracy
# economy). DENIES reading/searching repo source via grep/egrep/fgrep/rg/ag/ack and
# cat/sed/head/tail. ALLOWS everything else: stdin pipes, log/state/tmp/proc targets,
# non-source files, source files OUTSIDE the repo (jcode can't help), in-place edits
# (sed -i), and ALL output redirections / heredocs (writes — incl. the pre-mortem
# audit sink and clearance-token flows).
#
# Detection is PER COMMAND-SEGMENT: a source file is only flagged when it is an argument
# to THAT segment's read-tool command. So `pytest a.py | tail -8` is allowed (a.py is
# pytest's arg; tail reads stdin), while `cat a.py | grep x` is denied (cat reads a.py).
# Behaviour is pinned by tests/test_grep_guard.py.
set -uo pipefail

# Projects root differs by platform: /opt/proj on Linux, /c/opt/proj under Git
# Bash (MSYS maps C:\ to /c). REPO_ROOT drives the "is this path inside the repo
# tree?" test below, so a wrong value does not error — it makes every absolute
# path look external and the guard silently allows what it should deny. Probe
# instead of hardcoding.
# Both spellings are treated as in-repo regardless of which platform we are on:
# the test is a containment check, and denying a path that happens not to exist
# here costs nothing, while missing one silently allows a source read.
PROJ_ROOTS="${UNCLE_J_PROJ_ROOT:+$UNCLE_J_PROJ_ROOT }/opt/proj /c/opt/proj"
# Fallback scope only. Once the payload is parsed, SESSION_ROOT (the git toplevel
# of the session's cwd, see session_repo_root below) replaces it — "this repo" in the
# block message. The projects root stays the fallback so a missing or unusable cwd
# fails closed rather than open.
REPO_ROOTS="$PROJ_ROOTS"
SESSION_ROOT=""   # held apart from the word-split list: a toplevel may contain spaces

in_repo() {
  local p="$1" r
  if [[ -n "$SESSION_ROOT" ]]; then
    case "$p" in "$SESSION_ROOT"/*) return 0 ;; esac
    return 1
  fi
  for r in $REPO_ROOTS; do
    case "$p" in "$r"/*) return 0 ;; esac
  done
  return 1
}

# LOG must point at a directory that exists, so pick the root actually present.
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

# jq is required. Without it the parse below yields an empty CMD and the guard
# exits 0 — allowing every command it exists to screen. Fail loudly instead.
if ! command -v jq >/dev/null 2>&1; then
  echo "grep-guard: jq not found on PATH — guard cannot evaluate commands" >&2
  exit 1
fi

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo "unknown")

# Scope "the repo" to the session's own repo: jcodemunch serves the project being
# worked on, so another project's source read from this session is "outside the
# repo" (2026-10-16: /opt/proj/voice-line reads from a Refinery session were denied).
# Git Bash prints the toplevel as C:/..., which never prefix-matches the /c/...
# spelling of a command's paths and would make every path look external — fail
# open. cygpath -u normalises it; anything that still isn't absolute is discarded.
session_repo_root() {
  local cwd top
  cwd=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
  [[ -n "$cwd" && -d "$cwd" ]] || return 1
  top=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) || return 1
  if command -v cygpath >/dev/null 2>&1; then
    top=$(cygpath -u "$top" 2>/dev/null) || return 1
  fi
  [[ "$top" == /?* ]] || return 1
  printf '%s' "$top"
}
SESSION_ROOT=$(session_repo_root) || SESSION_ROOT=""

log_entry() { hook_log_append "$LOG" "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

[[ -z "${CMD:-}" ]] && exit 0

# A heredoc means the command is WRITING (e.g. `cat >> audit.md <<'EOF'`) — allow outright.
echo "$CMD" | grep -qE '<<' && exit 0

# Strip a trailing shell comment so an allowed path named in a comment cannot exempt a
# real source grep (the old whole-command substring-exception bug).
CMD_CLEAN=$(printf '%s' "$CMD" | sed -E 's/[[:space:]]+#.*$//')

ALLOWED_RE='(/tmp/|/proc/|/var/log/|(^|[^[:alnum:]_])state/|\.log([^[:alnum:]]|$)|\.code-index|hook-blocks)'
SRC_EXT='\.(py|sh|bash|js|mjs|cjs|jsx|ts|tsx|go|rs|rb|php|java|c|h|cpp|hpp|swift|kt|lua|pl)([^[:alnum:]]|$)'

# Split into command segments on  &&  ||  |  ;  &  (and newlines already split rows).
SEGMENTS=$(printf '%s' "$CMD_CLEAN" | sed -E 's/(&&|\|\||;|&|\|)/\n/g')

# rg/ag/ack are recursive-by-default: a segment whose command IS one of them and that has
# no allowed-location reference reads the source tree. (When piped into — `ps | rg foo` —
# the split puts rg first-word in its own segment with no path; we still allow that because
# such a segment has neither an explicit non-allowed path nor a recursive filesystem intent
# we can confirm. Explicit `rg foo scripts/` is caught by the per-segment path scan below.)
deny=0

while IFS= read -r seg; do
  [[ -z "${seg// /}" ]] && continue

  set -f; set -- $seg; set +f
  cmd0="${1:-}"
  base="${cmd0##*/}"            # /usr/bin/grep -> grep

  case "$base" in
    grep|egrep|fgrep|cat|head|tail|sed) ;;   # rg/ag/ack handled at whole-command level below
    *) continue ;;             # this segment's command is not a read tool → ignore its args
  esac

  # sed -i / --in-place is an EDIT (write), not a read.
  if [[ "$base" == sed ]] && echo "$seg" | grep -qE 'sed[[:space:]]+(-[a-zA-Z]*i|--in-place)'; then
    continue
  fi

  # Recursive grep: an actual -r/-R flag TOKEN reads a directory tree. Flag detection is
  # per-token, not whole-segment: hyphenated words in patterns or paths ("-MORTEM",
  # "/…/-opt-proj-…/MEMORY.md", "ytd-angel-pr-pin") are NOT flags.
  if [[ "$base" == grep || "$base" == egrep || "$base" == fgrep ]]; then
    recursive=0
    set -f
    for tok in $seg; do
      case "$tok" in
        --recursive|--dereference-recursive) recursive=1; break ;;
        --*) ;;                                            # long option, not recursive
        -*[rR]*) echo "$tok" | grep -qE '^-[a-zA-Z]+$' && { recursive=1; break; } ;;
      esac
    done
    set +f
    if [[ $recursive -eq 1 ]]; then
      echo "$seg" | grep -qE "$ALLOWED_RE" && continue
      # Deny only when a path operand can reach the repo tree. Walk the operands:
      # skip the command, flag tokens, redirects, detached numeric flag values, and
      # the first non-flag arg (the search pattern). Absolute/~ paths OUTSIDE the
      # repo are allowed (jcode can't help there); relative paths resolve in the
      # repo cwd and no-path means cwd itself → deny both.
      first=1; pattern_seen=0; has_path=0; repo_path=0
      set -f
      for tok in $seg; do
        if [[ $first -eq 1 ]]; then first=0; continue; fi
        [[ "$tok" == -* ]] && continue
        [[ "$tok" == *">"* ]] && continue
        if [[ $pattern_seen -eq 0 ]]; then pattern_seen=1; continue; fi
        # After the pattern slot is filled, a bare numeral is a detached flag
        # value (`-A 3`), not a path. Checked after pattern_seen so a numeric
        # PATTERN (`grep -rl 500 /home/...`) can't swallow the path operand.
        echo "$tok" | grep -qE '^[0-9]+$' && continue
        has_path=1
        if in_repo "$tok"; then
          repo_path=1
        else
          case "$tok" in
            /*|"~"*) ;;
            *) repo_path=1 ;;
          esac
        fi
      done
      set +f
      if [[ $has_path -eq 0 || $repo_path -eq 1 ]]; then deny=1; break; fi
      continue
    fi
  fi

  # Scan THIS segment's tokens for a source file being READ. Skip the command itself,
  # flag tokens (--include=*.sh is a filter, not a file), and — for pattern-taking tools
  # (grep family, sed) — the first non-flag argument, which is the pattern/script text
  # ("ytd\.sh", 's/foo.py/bar/'), not a file operand.
  pattern_pending=0
  case "$base" in grep|egrep|fgrep|sed) pattern_pending=1 ;; esac
  set -f; prev=""; first=1
  for tok in $seg; do
    if [[ $first -eq 1 ]]; then first=0; prev="$tok"; continue; fi
    if [[ "$tok" == -* ]]; then prev="$tok"; continue; fi
    if [[ $pattern_pending -eq 1 && "$tok" != ">"* && "$prev" != ">" && "$prev" != ">>" ]]; then
      pattern_pending=0; prev="$tok"; continue
    fi
    if echo "$tok" | grep -qE "$SRC_EXT"; then
      [[ "$prev" == ">" || "$prev" == ">>" || "$tok" == ">"* ]] && { prev="$tok"; continue; }   # redirect target
      echo "$tok" | grep -qE "$ALLOWED_RE" && { prev="$tok"; continue; }                          # allowed location
      # Source OUTSIDE the repo — jcode can't help there, so allow it. The guard sees the
      # RAW unexpanded command string, so a `~/…` operand never arrives as `/…`. Matching
      # only /* silently denied every home-dir source read (e.g. `grep -n foo
      # ~/.claude/hooks/discipline/grep-guard.sh`) while the identical /home/bill/…
      # spelling was allowed. Expand ~ to $HOME first, then apply the same containment
      # test to both spellings. The recursive branch above also accepts both — keep in sync.
      case "$tok" in
        "~"|"~"/*) probe="${HOME:-}${tok#\~}" ;;
        *)         probe="$tok" ;;
      esac
      [[ "$probe" == /* ]] && ! in_repo "$probe" && { prev="$tok"; continue; }                   # source outside repo
      deny=1; break
    fi
    prev="$tok"
  done
  set +f
  [[ $deny -eq 1 ]] && break
done <<< "$SEGMENTS"

# rg/ag/ack are recursive-by-default. Treat as a source search when invoked in command
# position EXCLUDING after a pipe (a piped `… | rg foo` reads stdin, not the tree) and
# with no allowed-location target.
if [[ $deny -eq 0 ]] \
   && echo "$CMD_CLEAN" | grep -qE '(^|[;&(])[[:space:]]*(rg|ag|ack)\b' \
   && ! echo "$CMD_CLEAN" | grep -qE "$ALLOWED_RE"; then
  deny=1
fi

[[ $deny -eq 0 ]] && exit 0

# Collapse newlines/tabs BEFORE truncating: `head -c` cuts bytes, not lines, so a
# multi-line $CMD wrote N lines into the log and only the last carried `session=`.
# That silently broke one-entry-per-line parsing for the weekly review (385 of 3452
# lines were continuation junk). tr first, then truncate the now-single line.
log_entry "BLOCKED grep-guard cmd=$(printf '%s' "$CMD" | tr '\n\r\t' ' ' | head -c 120) session=$SESSION_ID"

REASON="Reading/searching repo source via shell is blocked — use jcodemunch (saves tokens, returns ranked structured results):

  • content/regex search  → mcp__jcodemunch__search_text(query=\"...\", repo=<repo>)
  • read a function/symbol → mcp__jcodemunch__get_symbol_source / get_context_bundle
  • read/outline a file    → mcp__jcodemunch__get_file_outline / get_file_content

Allowed without jcode: stdin pipes (… | grep), logs/state/tmp/proc targets, non-source
files, source outside this repo, and writes (redirects/heredocs/sed -i).

Find the repo id with mcp__jcodemunch__list_repos(). Logged to state/hook-blocks.log"

jq -n --arg r "$REASON" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": $r
  }
}'

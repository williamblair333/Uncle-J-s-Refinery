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

LOG="/opt/proj/Uncle-J-s-Refinery/state/hook-blocks.log"
REPO_ROOT="/opt/proj"

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo "unknown")

log_entry() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG" 2>/dev/null || true; }

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

  # Recursive grep: `grep -r` reads a directory tree of source.
  if [[ "$base" == grep || "$base" == egrep || "$base" == fgrep ]] \
     && echo "$seg" | grep -qE '(-[a-zA-Z]*r[a-zA-Z]*|--recursive)\b'; then
    echo "$seg" | grep -qE "$ALLOWED_RE" && continue
    deny=1; break
  fi

  # Scan THIS segment's tokens for a source file being read.
  set -f; prev=""
  for tok in $seg; do
    if echo "$tok" | grep -qE "$SRC_EXT"; then
      [[ "$prev" == ">" || "$prev" == ">>" || "$tok" == ">"* ]] && { prev="$tok"; continue; }   # redirect target
      echo "$tok" | grep -qE "$ALLOWED_RE" && { prev="$tok"; continue; }                          # allowed location
      [[ "$tok" == /* && "$tok" != ${REPO_ROOT}/* ]] && { prev="$tok"; continue; }                # source outside repo
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

log_entry "BLOCKED grep-guard cmd=$(echo "$CMD" | head -c 120) session=$SESSION_ID"

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

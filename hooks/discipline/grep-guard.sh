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
ROOTS=()          # the in-repo roots, each in its literal AND symlink-resolved spelling
CWD_REAL=""       # the session's cwd, resolved — anchors relative operands
IN_REPO_REL=""    # set by in_repo(): the matched path relative to its root

# Symlink- and `..`-resolved spelling of an ABSOLUTE path that need not exist
# (`realpath -m`). in_repo() used to be a literal string-prefix test, so repo source
# reached through a symlink (~/.claude/hooks/discipline/grep-guard.sh -> this repo)
# or a `..` hop through an allowed dir (/tmp/../opt/proj/<repo>/x.py) looked
# external. If realpath is missing or fails, return the input unchanged: that is the
# old literal behaviour, never anything looser.
resolve_path() {
  local r
  r=$(realpath -m -- "$1" 2>/dev/null) || r=""
  if [[ "$r" == /* ]]; then printf '%s' "$r"; else printf '%s' "$1"; fi
}

# True when the path — literal OR resolved spelling — is a repo root or below one.
in_repo() {
  local p="$1" rp c r
  IN_REPO_REL=""
  rp=$(resolve_path "$p")
  for c in "$p" "$rp"; do
    for r in "${ROOTS[@]}"; do
      [[ -z "$r" ]] && continue
      if [[ "$c" == "$r" ]]; then IN_REPO_REL=""; return 0; fi
      case "$c" in "$r"/*) IN_REPO_REL="${c#"$r"/}"; return 0 ;; esac
    done
  done
  return 1
}

# True when a recursive search rooted at this path would walk a repo root
# (`grep -rn foo /opt/proj/` from a session in /opt/proj/<repo>).
is_repo_ancestor() {
  local rp r
  rp=$(resolve_path "$1"); rp="${rp%/}"
  for r in "${ROOTS[@]}"; do
    [[ -z "$r" ]] && continue
    [[ -z "$rp" ]] && return 0                       # "/" itself
    case "$r" in "$rp"/*) return 0 ;; esac
  done
  return 1
}

# Absolute spelling of a path operand, or nothing when it can't be known. `~` and
# `~/…` expand to $HOME (the guard sees the RAW command); relative operands are
# anchored at the session cwd when there is one. `~user/…` stays unknown.
abs_of() {
  local t="$1"
  case "$t" in
    "~"|"~"/*) t="${HOME:-}${t#\~}" ;;
    "~"*) return 0 ;;
  esac
  if [[ "$t" == /* ]]; then printf '%s' "$t"
  elif [[ -n "$CWD_REAL" ]]; then printf '%s' "$CWD_REAL/$t"
  fi
}

# An allowed (non-source) location, judged on where the path LANDS: the literal
# token must match ALLOWED_RE, and if it resolves into the repo, the repo-relative
# resolved remainder must match too. So state/x.py stays allowed, while
# /tmp/link.py -> <repo>/scripts/x.py and scripts/hook-blocks/../x.py do not.
allowed_loc() {
  local t="$1" a rp
  printf '%s' "$t" | grep -qE "$ALLOWED_RE" || return 1
  a=$(abs_of "$t"); [[ -z "$a" ]] && return 0
  rp=$(resolve_path "$a")
  in_repo "$rp" || return 0
  # realpath drops a trailing slash, and ALLOWED_RE needs one on `state/`.
  local rel="$IN_REPO_REL"
  [[ "$t" == */ || -d "$rp" ]] && rel="$rel/"
  printf '%s' "$rel" | grep -qE "$ALLOWED_RE"
}

# LOG must point at a directory that exists, so pick the root actually present.
LOG_ROOT=/opt/proj
for _cand in $PROJ_ROOTS; do
  [ -d "$_cand" ] && { LOG_ROOT="$_cand"; break; }
done
LOG="$LOG_ROOT/Uncle-J-s-Refinery/state/hook-blocks.log"

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

if [[ -n "$SESSION_ROOT" ]]; then
  ROOTS=("$SESSION_ROOT" "$(resolve_path "$SESSION_ROOT")")
else
  for _r in $REPO_ROOTS; do ROOTS+=("$_r" "$(resolve_path "$_r")"); done
fi

# The session cwd, resolved the same way, so relative operands can be resolved
# against it. Unknown cwd leaves relative operands judged as before (in-repo).
_cwd=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
if [[ -n "$_cwd" && -d "$_cwd" ]]; then
  if command -v cygpath >/dev/null 2>&1; then _cwd=$(cygpath -u "$_cwd" 2>/dev/null) || _cwd=""; fi
  [[ "$_cwd" == /* ]] && CWD_REAL=$(resolve_path "$_cwd")
fi
unset _cwd _r

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
      # Deny only when a path operand can reach the repo tree. Walk the operands:
      # skip the command, flag tokens, redirects, detached numeric flag values, and
      # the first non-flag arg (the search pattern). Absolute/~ paths OUTSIDE the
      # repo are allowed (jcode can't help there); relative paths resolve in the
      # repo cwd and no-path means cwd itself → deny both.
      # Allowed locations are judged PER OPERAND (allowed_loc). The old whole-segment
      # ALLOWED_RE test let `grep -rn foo scripts/ /tmp/` through on the /tmp/ alone.
      # Exception: every --include filter naming an allowed kind (`--include=*.log`)
      # means only those files are read, whatever the tree.
      first=1; pattern_seen=0; has_path=0; repo_path=0; inc_any=0; inc_bad=0
      set -f
      for tok in $seg; do
        if [[ $first -eq 1 ]]; then first=0; continue; fi
        case "$tok" in
          --include=*)
            inc_any=1
            printf '%s' "${tok#--include=}" | grep -qE "$ALLOWED_RE" || inc_bad=1
            continue ;;
        esac
        [[ "$tok" == -* ]] && continue
        [[ "$tok" == *">"* ]] && continue
        if [[ $pattern_seen -eq 0 ]]; then pattern_seen=1; continue; fi
        # After the pattern slot is filled, a bare numeral is a detached flag
        # value (`-A 3`), not a path. Checked after pattern_seen so a numeric
        # PATTERN (`grep -rl 500 /home/...`) can't swallow the path operand.
        echo "$tok" | grep -qE '^[0-9]+$' && continue
        has_path=1
        allowed_loc "$tok" && continue
        case "$tok" in
          /*|"~"|"~"/*)
            probe=$(abs_of "$tok")
            if in_repo "$probe" || is_repo_ancestor "$probe"; then repo_path=1; fi ;;
          *) repo_path=1 ;;
        esac
      done
      set +f
      [[ $inc_any -eq 1 && $inc_bad -eq 0 ]] && continue
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
    # A token is source when its literal spelling has a source extension, OR when it
    # resolves (symlink) into the repo onto a file that has one — `cat /tmp/notes.txt`
    # where notes.txt -> <repo>/scripts/x.py is a source read.
    is_src=0
    printf '%s' "$tok" | grep -qE "$SRC_EXT" && is_src=1
    if [[ $is_src -eq 0 && "$tok" != ">"* && "$prev" != ">" && "$prev" != ">>" ]]; then
      probe=$(abs_of "$tok")
      if [[ -n "$probe" ]]; then
        rprobe=$(resolve_path "$probe")
        printf '%s' "$rprobe" | grep -qE "$SRC_EXT" && in_repo "$rprobe" && is_src=1
      fi
    fi
    if [[ $is_src -eq 1 ]]; then
      [[ "$prev" == ">" || "$prev" == ">>" || "$tok" == ">"* ]] && { prev="$tok"; continue; }   # redirect target
      allowed_loc "$tok" && { prev="$tok"; continue; }                                            # allowed location
      # Source OUTSIDE the repo — jcode can't help there, so allow it. The guard sees the
      # RAW unexpanded command string, so a `~/…` operand never arrives as `/…`. Matching
      # only /* silently denied every home-dir source read (e.g. `grep -n foo
      # ~/.claude/hooks/discipline/grep-guard.sh`) while the identical /home/bill/…
      # spelling was allowed. Expand ~ to $HOME first, then apply the same containment
      # test to both spellings. in_repo() also resolves symlinks, so a home-dir link
      # into this repo is in-repo under either spelling. Relative operands stay denied.
      # The recursive branch above uses the same helpers — keep in sync.
      case "$tok" in
        /*|"~"|"~"/*) probe=$(abs_of "$tok")
                      ! in_repo "$probe" && { prev="$tok"; continue; } ;;                     # source outside repo
      esac
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
# Operands are judged one by one with the same helpers as recursive grep: the old
# whole-command ALLOWED_RE test let `rg foo scripts/ /tmp/` and `rg foo /tmp/link`
# (link -> repo) through on the /tmp/ alone.
if [[ $deny -eq 0 ]] \
   && echo "$CMD_CLEAN" | grep -qE '(^|[;&(])[[:space:]]*(rg|ag|ack)\b'; then
  # Pipelines split on && || ; & — a single | is left inside, so stage 0 of each
  # pipeline is the command-position stage and later stages read stdin.
  PIPELINES=$(printf '%s' "$CMD_CLEAN" | sed -E 's/(&&|\|\||;|&)/\n/g')
  while IFS= read -r pl; do
    stage0="${pl%%|*}"
    stage0="${stage0#"${stage0%%[![:space:](]*}"}"     # strip leading space / (
    set -f; set -- $stage0; set +f
    case "${1##*/}" in rg|ag|ack) ;; *) continue ;; esac
    shift
    pattern_seen=0; has_path=0; repo_path=0; glob_any=0; glob_bad=0; want_val=""
    set -f
    for tok in "$@"; do
      if [[ -n "$want_val" ]]; then
        if [[ "$want_val" == glob ]]; then
          glob_any=1; printf '%s' "$tok" | grep -qE "$ALLOWED_RE" || glob_bad=1
        fi
        want_val=""; continue
      fi
      case "$tok" in
        -g|--glob|--iglob|-G) want_val=glob; continue ;;
        --glob=*|--iglob=*)
          glob_any=1; printf '%s' "${tok#*=}" | grep -qE "$ALLOWED_RE" || glob_bad=1; continue ;;
        -e|--regexp|-f|--file) pattern_seen=1; want_val=val; continue ;;   # pattern given by flag
        --regexp=*|--file=*) pattern_seen=1; continue ;;
        -t|-T|--type|--type-not|-A|-B|-C|-m|--max-count|-j|--threads|-M|--max-columns)
          want_val=val; continue ;;
        -*) continue ;;
        *">"*) continue ;;
      esac
      if [[ $pattern_seen -eq 0 ]]; then pattern_seen=1; continue; fi
      has_path=1
      allowed_loc "$tok" && continue
      case "$tok" in
        /*|"~"|"~"/*)
          probe=$(abs_of "$tok")
          if in_repo "$probe" || is_repo_ancestor "$probe"; then repo_path=1; fi ;;
        *) repo_path=1 ;;
      esac
    done
    set +f
    [[ $glob_any -eq 1 && $glob_bad -eq 0 ]] && continue
    if [[ $has_path -eq 0 || $repo_path -eq 1 ]]; then deny=1; break; fi
  done <<< "$PIPELINES"
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

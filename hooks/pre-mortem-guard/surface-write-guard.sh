#!/usr/bin/env bash
# Detects Bash commands that write to surface files, bypassing the Edit/Write tool guard.
# Catches: redirects (>), sed -i, python open-write, perl/ruby/node file writes, awk >, cp/mv.
# Note: no regex can be truly exhaustive — new interpreters or obfuscated writes are residual risk.
#
# WHY THIS EXISTS AS A REPO FILE
#
# It lived only as a real file under ~/.claude/hooks/pre-mortem-guard/, unlike its
# siblings grep-guard.sh and edit-surface-guard.sh which are symlinks into this repo.
# That put it outside install.sh and refinery-doctor --fix, so it was lost on a machine
# rebuild, and no PR could reach the two defects fixed below.
#
# The registered path is ~/.claude/hooks/pre-mortem-guard/surface-write-guard.sh, so this
# file is versioned under hooks/pre-mortem-guard/ (NOT hooks/discipline/) to match. The
# installer symlinks it to exactly that path; putting it in discipline/ would create a
# second, unregistered copy while the live one ran unchanged.
#
# The detection regexes below are byte-identical to the version they replace. A false
# negative on a write-guard is strictly worse than the logging bug being fixed, so only
# the jq check and the log line differ.

set -uo pipefail

# jq is required. Without it the parse below yields an empty CMD and the guard
# exits 0 — allowing every command it exists to screen. Fail loudly instead.
# (PreToolUse blocks on exit 2; exit 1 surfaces the error without trapping the
# call. Same posture as grep-guard.sh.)
if ! command -v jq >/dev/null 2>&1; then
  echo "surface-write-guard: jq not found on PATH — guard cannot evaluate commands" >&2
  exit 1
fi

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || echo "")
[[ -z "$CMD" ]] && exit 0

# Surface file extension/path patterns (mirrors is_surface() in edit-surface-guard.sh)
SURF_EXT='\.(sh|py|toml|yml|yaml|cfg|ini)'
SURF_PATH='(/hooks/|/scripts/|/features/)'
SURF_FILE='(settings\.json|CLAUDE\.md|Dockerfile)'

# Detect: redirect (> or >>) to surface-extension file or surface directory
# Matches: echo 'x' > file.sh, command > /hooks/foo.sh, etc.
REDIR_RE=">[>]?[[:space:]]*(\"[^\"]*${SURF_EXT}\"|'[^']*${SURF_EXT}'|[^[:space:]]*${SURF_EXT}[[:space:];|&$\"']|[^[:space:]]*${SURF_PATH}[^[:space:]]*|[^[:space:]]*${SURF_FILE}[[:space:];|&$\"'])"

# Detect: sed -i editing a surface file
SED_RE="sed[[:space:]]+-[a-zA-Z]*i[[:space:]a-zA-Z0-9='\"]*[[:space:]][^[:space:]]*${SURF_EXT}"

# Detect: python3 opening surface file in write mode
PY_RE="python3?[[:space:]].*open[[:space:]]*\([[:space:]]*['\"][^'\"]*${SURF_EXT}['\"][^)]*['\"][wa]['\"]"

# Detect: perl/ruby/node/awk touching a surface file path.
# Broad matching: any mention of surface path in these interpreter invocations.
# Better to have false positives than to miss writes.
PERL_RE="(^|[[:space:];|&(])perl[[:space:]].*(['\"][^'\"]*${SURF_EXT}['\"]|[^[:space:]]*${SURF_EXT}[[:space:];|&\$'\"(]|[^[:space:]]*${SURF_PATH}[^[:space:]]*)"
RUBY_RE="(^|[[:space:];|&(])ruby[[:space:]].*(['\"][^'\"]*${SURF_EXT}['\"]|[^[:space:]]*${SURF_EXT}[[:space:];|&\$'\"(]|[^[:space:]]*${SURF_PATH}[^[:space:]]*)"
NODE_RE="(^|[[:space:];|&(])node(js)?[[:space:]].*(['\"][^'\"]*${SURF_EXT}['\"]|[^[:space:]]*${SURF_EXT}[[:space:];|&\$'\"(]|[^[:space:]]*${SURF_PATH}[^[:space:]]*)"
AWK_RE="(^|[[:space:];|&(])awk[[:space:]].*>[[:space:]]*(['\"]?[^[:space:]]*${SURF_EXT}['\"]?|['\"]?[^[:space:]]*${SURF_PATH}[^[:space:]]*['\"]?)"

# Detect: cp/mv to a surface directory or surface extension
CP_RE="(cp|mv)[[:space:]].*[[:space:]](['\"]?[^[:space:]]*${SURF_EXT}['\"]?|['\"]?[^[:space:]]*${SURF_PATH}[^[:space:]]*['\"]?)"

# ── Scratch targets under /tmp are not surface writes (2026-10-16) ───────────────
# The regexes above match on text, so `cat > $scratchpad/probe.py` and a backup
# copied INTO scratch were blocked as surface writes. Before matching, remove the
# operands that provably resolve under /tmp; the regexes then run, unchanged, on
# what remains. Each exemption is narrow because a write guard's false negative is
# worse than its false positive:
#   * operand = plain path characters only, so `>/tmp/a;cp …` can't swallow `cp`;
#   * resolved with realpath -m, so `/tmp/../…` and existing symlinks out of /tmp
#     stay in the scan; `ln` anywhere in the command disables the exemption, since a
#     link created by this very command doesn't exist yet to be resolved;
#   * `mv` anywhere disables it too: `mv repo/x.py /tmp/x.bak` writes /tmp but
#     deletes the surface source, and CP_RE only sees non-first operands;
#   * a `$VAR` is expanded only when VAR is assigned exactly once, as a statement of
#     its own (`S=/tmp/x;` — not the `S=/tmp/x cmd` prefix form, which doesn't bind
#     for the redirect), to a quote-balanced /tmp value, in a command with nothing
#     that can rebind it without a literal `VAR=` (loops, read, printf -v, eval, …);
#   * removal is per whole operand, line by line — never a substring replace, which
#     would also strip `/tmp/foo` out of `…/hooks/tmp/foo`;
#   * the pre-mortem token path is never exempt.

# ── A `cat` heredoc's body is data, not commands (2026-10-16) ────────────────────
# Notes and audit records that merely MENTION a redirect-shaped path were blocked.
# The body is dropped from the scan only when it can't be executed: the heredoc's
# command is `cat`, the `<<` is real (unquoted, unescaped, the only one on the
# line) and the line has no pipe, $( or backtick that could feed the body to a
# shell. `bash <<EOF`, `cat <<EOF | bash` and `bash -c "$(cat <<EOF…)"` stay
# scanned. The line holding `<<`, so the write target, is always scanned.
strip_cat_heredoc_bodies() {
  local line delim="" dash=0 out="" pre seg w rest cmp
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ -n "$delim" ]]; then
      cmp="$line"
      [[ $dash -eq 1 ]] && cmp="${line#"${line%%[!$'\t']*}"}"
      [[ "$cmp" == "$delim" ]] && delim=""
      continue
    fi
    out+="$line"$'\n'
    [[ "$line" == *"<<"* ]] || continue
    # A trailing `\` continues the command onto the next line, so the body starts
    # later than this line suggests — don't guess, keep scanning.
    [[ "$line" == *\\ ]] && continue
    [[ $(printf '%s' "$line" | grep -o '<<' | wc -l) -eq 1 ]] || continue
    [[ "$line" == *"|"* || "$line" == *'$('* || "$line" == *'`'* ]] && continue
    pre=${line%%<<*}
    [[ "$pre" == *\\ ]] && continue
    local dq=${pre//[^\"]/} sq=${pre//[^\']/}
    (( ${#dq} % 2 == 0 && ${#sq} % 2 == 0 )) || continue
    seg=${pre##*[;&(]}
    read -r w _ <<< "$seg"
    [[ "$w" == cat ]] || continue
    rest=${line#*<<}; dash=0
    [[ "$rest" == -* ]] && { dash=1; rest=${rest#-}; }
    # The delimiter must be exactly 'WORD', "WORD" or WORD, then a word break.
    # Bash joins pieces (`E"OF"` is EOF); reading only the first piece would end
    # the body somewhere bash doesn't.
    [[ "$rest" =~ $HEREDOC_DELIM_RE ]] || continue
    delim="${BASH_REMATCH[2]}${BASH_REMATCH[3]}${BASH_REMATCH[4]}"
  done <<< "$1"
  printf '%s' "$out"
}
HEREDOC_DELIM_RE="^[[:space:]]*('([A-Za-z_][A-Za-z0-9_]*)'|\"([A-Za-z_][A-Za-z0-9_]*)\"|([A-Za-z_][A-Za-z0-9_]*))([[:space:];>&)]|\$)"

# A CR is part of a word to bash (`EOF\r` is the delimiter), so with CRLF input the
# body would end where this parser can't see it. No stripping then.
if [[ "$CMD" == *$'\r'* ]]; then SCAN="$CMD"; else SCAN=$(strip_cat_heredoc_bodies "$CMD"); fi
# The body is code again if anything left in the command can execute it: write a
# script then run it, `> >(bash)`, `exec 3> >(sh)` then `>&3`, `./file`. Any
# shell, interpreter or exec word outside the bodies → scan the bodies after all.
EXEC_RE='(^|[^[:alnum:]_./-])(bash|sh|zsh|dash|ksh|fish|source|exec|eval|xargs|python[0-9.]*|perl|ruby|node|php|lua|tclsh|env|sudo|su)([^[:alnum:]_.-]|$)|(^|[^[:alnum:]_.])\./|(^|[;&|(])[[:space:]]*\.[[:space:]]'
if [[ "$SCAN" != "$CMD"$'\n' && "$SCAN" != "$CMD" ]] && printf '%s' "$SCAN" | grep -qE "$EXEC_RE"; then
  SCAN="$CMD"
fi
if ! printf '%s' "$CMD" | grep -qE '(^|[^[:alnum:]_.-])(ln|mv)[[:space:]]'; then
  if ! printf '%s' "$CMD" | grep -qE '(^|[^[:alnum:]_])(for|read|mapfile|readarray|declare|local|typeset|eval|printf[[:space:]]+-v|getopts|unset|source|let)[[:space:]]|(^|[;&|(])[[:space:]]*\.[[:space:]]|\(\('; then
    while IFS= read -r asg; do
      [[ -z "$asg" ]] && continue
      asg=${asg#export }
      var=${asg%%=*}; raw=${asg#*=}; val=$raw
      case "$raw" in
        \"*) [[ ${#raw} -gt 1 && "$raw" == *\" ]] || continue; val=${raw:1:${#raw}-2} ;;
        \'*) [[ ${#raw} -gt 1 && "$raw" == *\' ]] || continue; val=${raw:1:${#raw}-2} ;;
      esac
      [[ "$val" =~ ^/tmp/[A-Za-z0-9._/+@%:,=-]*$ ]] || continue
      n=$(printf '%s' "$CMD" | grep -oE "(^|[^[:alnum:]_])${var}\+?=" | wc -l)
      [[ "$n" -eq 1 ]] || continue
      SCAN=${SCAN//"\${$var}"/$val}
      SCAN=${SCAN//"\$$var/"/$val/}
    # Statement-form assignments only: at line start or after ; & | (, and followed by
    # end of statement. grep -o is per line, so ^ and $ are line boundaries.
    done < <(printf '%s' "$CMD" \
      | grep -oE "(^|[;&|(])[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=[^[:space:];&|)]+[[:space:]]*(;|&&|\|\||$)" \
      | sed -E 's/^[;&|(]?[[:space:]]*//; s/[[:space:]]*(;|&&|\|\|)?$//')
  fi
  OUT=""
  set -f
  while IFS= read -r line || [[ -n "$line" ]]; do
    newline=""
    for tok in $line; do
      keep="$tok"
      pre=${tok%%/tmp/*}                      # redirect/quote prefix, e.g. `>` `2>` `"`
      if [[ "$pre" =~ ^[0-9]?\>{0,2}[\"\']?$ ]]; then
        t=${tok:${#pre}}; t=${t%\"}; t=${t%\'}
        if [[ "$t" =~ ^/tmp/[A-Za-z0-9._/+@%:,=-]+$ ]]; then
          r=$(realpath -m -- "$t" 2>/dev/null) || r=""
          if [[ "$r" == /tmp/?* && "$r" != /tmp/premortem-cleared* ]]; then
            keep="${pre%[\"\']}"
          fi
        fi
      fi
      newline+="${newline:+ }$keep"
    done
    # No trailing space: REDIR_RE needs a delimiter after the filename, so padding the
    # line end would silently change what the regexes detect (see KNOWN_GAPS).
    OUT+="$newline"$'\n'
  done <<< "$SCAN"
  set +f
  SCAN="$OUT"
fi

HIT=0
echo "$SCAN" | grep -qE "$REDIR_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$SCAN" | grep -qE "$SED_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$SCAN" | grep -qE "$PY_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$SCAN" | grep -qE "$PERL_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$SCAN" | grep -qE "$RUBY_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$SCAN" | grep -qE "$NODE_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$SCAN" | grep -qE "$AWK_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$SCAN" | grep -qE "$CP_RE" && HIT=1

[[ $HIT -eq 0 ]] && exit 0

SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo "unknown")

# LOG must point at a directory that exists, so pick the root actually present.
LOG_ROOT=/opt/proj
for _cand in /opt/proj /c/opt/proj; do
  [ -d "$_cand" ] && { LOG_ROOT="$_cand"; break; }
done
LOG="${SURFACE_GUARD_LOG:-$LOG_ROOT/Uncle-J-s-Refinery/state/hook-blocks.log}"

# Collapse newlines/tabs BEFORE truncating: `head -c` cuts bytes, not lines, so a
# multi-line $CMD wrote N lines into the log and only the last carried `session=`.
# A block that cannot be found by searching for its own session is a block that
# cannot be audited — this guard's own entry on 2026-08-15 spilled across four
# physical lines with `session=` stranded on the fourth, and was reported as
# "fired but logged nothing". Same defect fixed in grep-guard.sh by PR #106.
# tr first, then truncate the now-single line.
echo "$(date '+%Y-%m-%d %H:%M:%S') BLOCKED surface-write-guard bash-writes-surface cmd=$(printf '%s' "$CMD" | tr '\n\r\t' ' ' | head -c 200) session=$SESSION_ID" >> "$LOG" 2>/dev/null || true

jq -n '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "BLOCKED: Bash write to surface file detected.\n\nThis bypasses the Edit/Write tool guard. Use the Edit or Write Claude tools instead — they enforce the pre-mortem requirement.\n\nIf this is a legitimate authorized operation (e.g., bootstrap security fix), state so explicitly and confirm pre-mortem was completed for this task."
  }
}'
exit 0

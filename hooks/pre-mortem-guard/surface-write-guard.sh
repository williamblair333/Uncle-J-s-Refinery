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
# Detection changes are pinned by tests/test_surface_write_guard.py: every widening
# (2026-10-22: end-of-command targets, GNU sed -i, cp/mv word boundary) carries both
# BLOCK cases and the ALLOW cases it must not break. A false negative on a write-guard
# is worse than a false positive, but a false positive still blocks real work.

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
# (2026-10-23) +service/timer, +.mcp.json, settings.local.json, justfile — the same
# additions as edit-surface-guard.sh (see its surface-list note). Its tests/test_*.py
# narrowing is NOT mirrored: this guard matches raw text, and a Bash write to a test
# file is rare enough (and the Edit tool the documented route) not to justify it.
SURF_EXT='\.(sh|py|toml|yml|yaml|cfg|ini|service|timer)'
SURF_PATH='(/hooks/|/scripts/|/features/)'
SURF_FILE='(settings\.json|settings\.local\.json|\.mcp\.json|CLAUDE\.md|Dockerfile|justfile)'
# What may follow a surface filename: anything that can't continue it, or end of line.
# (2026-10-22) This used to be a REQUIRED character from [[:space:];|&$"'], so a write
# at the very end of a command — `echo x >> setup.sh` — had nothing to match and was
# allowed, as was `(echo x > a.sh)`. `.` `-` `_` and alphanumerics still continue the
# name, so `a.sh.bak`, `a.shell` and `CLAUDE.md.orig` stay out.
SURF_END='([^[:alnum:]_.-]|$)'
# A surface target anywhere in a command segment (used by the sed check).
SURF_TOKEN_RE="(${SURF_EXT}${SURF_END}|${SURF_PATH}|${SURF_FILE}${SURF_END})"

# Detect: redirect (> or >>) to surface-extension file or surface directory
# Matches: echo 'x' > file.sh, command > /hooks/foo.sh, etc. Also the noclobber
# override `>| f.sh` and `>& f.sh` (2026-10-22: both were missed).
REDIR_RE=">[>|&]?[[:space:]]*(\"[^\"]*${SURF_EXT}\"|'[^']*${SURF_EXT}'|[^[:space:]]*${SURF_EXT}${SURF_END}|[^[:space:]]*${SURF_PATH}[^[:space:]]*|[^[:space:]]*${SURF_FILE}${SURF_END})"

# Detect: sed in-place (-i, -i.bak, -Ei, -i -e …, --in-place[=SUF], -i after the
# script — GNU permutes options). Matched per command SEGMENT (see SEGS below), and a
# segment that matches SED_RE is blocked only if it also names a surface target
# (SURF_TOKEN_RE). (2026-10-22) The old pattern allowed only [[:space:]a-zA-Z0-9='"]
# between the flag and the file, so `s/a/b/` or `-i.bak` killed the match and it fired
# on nothing but macOS `sed -i "" f.sh`.
# (2026-11-03) The flag must sit in sed's own pipeline stage: `[^|]*`, not `.*`, so
# `sed -n p f.yaml | grep -i x` is not an in-place edit. SEGS masks every `|` that
# isn't a stage boundary of the outer command (quoted, escaped, or inside $( ) <( )
# >( ) or backticks), so `sed 's|a|b|' -i f.sh` and `s/a\|b/` keep the span whole.
SED_RE="(^|[^[:alnum:]_.-])g?sed[\"']?[[:space:]]([^|]*[[:space:]])?[\"']?(-[a-zA-Z]*i|--in-place)"

# Detect: python3 opening surface file in write mode
PY_RE="python3?[[:space:]].*open[[:space:]]*\([[:space:]]*['\"][^'\"]*${SURF_EXT}['\"][^)]*['\"][wa]['\"]"

# Detect: perl/ruby/node/awk touching a surface file path.
# Broad matching: any mention of surface path in these interpreter invocations.
# Better to have false positives than to miss writes.
PERL_RE="(^|[[:space:];|&(])perl[[:space:]].*(['\"][^'\"]*${SURF_EXT}['\"]|[^[:space:]]*${SURF_EXT}${SURF_END}|[^[:space:]]*${SURF_PATH}[^[:space:]]*)"
RUBY_RE="(^|[[:space:];|&(])ruby[[:space:]].*(['\"][^'\"]*${SURF_EXT}['\"]|[^[:space:]]*${SURF_EXT}${SURF_END}|[^[:space:]]*${SURF_PATH}[^[:space:]]*)"
NODE_RE="(^|[[:space:];|&(])node(js)?[[:space:]].*(['\"][^'\"]*${SURF_EXT}['\"]|[^[:space:]]*${SURF_EXT}${SURF_END}|[^[:space:]]*${SURF_PATH}[^[:space:]]*)"
AWK_RE="(^|[[:space:];|&(])awk[[:space:]].*>[[:space:]]*(['\"]?[^[:space:]]*${SURF_EXT}['\"]?|['\"]?[^[:space:]]*${SURF_PATH}[^[:space:]]*['\"]?)"

# Detect: cp/mv to a surface directory or surface extension.
# (2026-10-22) cp/mv must start a word — line start, whitespace, ; | & ( ` or a path
# slash (/bin/cp) or backslash (\cp). Unanchored, the `cp` inside `claude mcp add …
# scripts/x.py` and `partikus_mcp … tests/x.py` was read as a copy.
# (2026-11-03) Matched per command SEGMENT and only up to the next stage pipe, like
# SED_RE: on the whole line `.*` ran past `&&` and `;`, so `mv a.jsonl b.jsonl &&
# dcup -f docker-compose.yml` was read as a move onto a .yml.
# (2026-11-04) Also a RELATIVE surface directory operand (`scripts/`, `./hooks/x`):
# SURF_PATH needs a leading `/`, so `mv x/*.py scripts/` was never checked. Replay over
# 12,480 transcript commands: +4 denies, all that real move; 0 false positives.
CP_RE="(^|[[:space:];|&(\`/\\])(cp|mv)[[:space:]][^|]*[[:space:]](['\"]?[^[:space:]]*${SURF_EXT}['\"]?|['\"]?[^[:space:]]*${SURF_PATH}[^[:space:]]*['\"]?|['\"]?(\./)?(hooks|scripts|features)/[^[:space:]]*['\"]?)"

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
# heredoc_body_mask MODE TEXT prints one char per line of TEXT: `b` for a heredoc body
# line, `o` for every other line (the delimiter line counts as body).
#   MODE=cat    — bodies of `cat` heredocs, any delimiter quoting (see above).
#   MODE=quoted — bodies of ANY command's heredoc whose delimiter is fully quoted
#                 ('EOF' / "EOF"). Bash doesn't expand such a body, so nothing in it
#                 runs in the current shell: it can't rebind a variable there (used by
#                 the $VAR exemption below, 2026-11-01).
# Every bail-out leaves lines as `o`, i.e. treated as commands.
heredoc_body_mask() {
  local mode=$1 line delim="" dash=0 out="" pre seg w rest cmp
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ -n "$delim" ]]; then
      out+="b"
      cmp="$line"
      [[ $dash -eq 1 ]] && cmp="${line#"${line%%[!$'\t']*}"}"
      [[ "$cmp" == "$delim" ]] && delim=""
      continue
    fi
    out+="o"
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
    if [[ "$mode" == cat ]]; then
      seg=${pre##*[;&(]}
      read -r w _ <<< "$seg"
      [[ "$w" == cat ]] || continue
    fi
    rest=${line#*<<}; dash=0
    [[ "$rest" == -* ]] && { dash=1; rest=${rest#-}; }
    # The delimiter must be exactly 'WORD', "WORD" or WORD, then a word break.
    # Bash joins pieces (`E"OF"` is EOF); reading only the first piece would end
    # the body somewhere bash doesn't.
    [[ "$rest" =~ $HEREDOC_DELIM_RE ]] || continue
    [[ "$mode" == quoted && -n "${BASH_REMATCH[4]}" ]] && continue
    delim="${BASH_REMATCH[2]}${BASH_REMATCH[3]}${BASH_REMATCH[4]}"
  done <<< "$2"
  printf '%s' "$out"
}

# Print the lines of TEXT whose MASK char is not `b` (MASK from heredoc_body_mask).
mask_keep_outer() {
  local mask=$1 line out="" i=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "${mask:i:1}" == b ]] || out+="$line"$'\n'
    i=$((i + 1))
  done <<< "$2"
  printf '%s' "$out"
}

strip_cat_heredoc_bodies() {
  mask_keep_outer "$(heredoc_body_mask cat "$1")" "$1"
}

# True when TEXT has a heredoc whose body this file can't delimit: two `<<` on one
# line, or a delimiter with quoting other than a plain 'WORD' / "WORD" (`<<\EOF`,
# `<<E'OF'`). Bash doesn't expand such a body, but the mask leaves it as outer text,
# so `$S` in it would be expanded with the outer value — and a child shell's `$S` is
# its own (`bash <<\EOF` + `${S}scripts/x.sh` writes ./scripts/x.sh). The $VAR
# exemption is skipped then. `<<<` here-strings are not heredocs.
heredoc_unsure() {
  local line rest n w
  while IFS= read -r line || [[ -n "$line" ]]; do
    line=${line//<<</}
    [[ "$line" == *"<<"* ]] || continue
    n=$(printf '%s' "$line" | grep -o '<<' | wc -l)
    [[ "$n" -ge 2 ]] && return 0
    rest=${line#*<<}; rest=${rest#-}
    rest="${rest#"${rest%%[![:space:]]*}"}"
    w=${rest%%[[:space:];&|)<>]*}
    if [[ "$w" == *[\\\'\"]* ]]; then
      [[ "$w" =~ ^\'[A-Za-z_][A-Za-z0-9_]*\'$ || "$w" =~ ^\"[A-Za-z_][A-Za-z0-9_]*\"$ ]] || return 0
    fi
  done <<< "$1"
  return 1
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
# A backslash-newline continues the command, and the regexes run one line at a time:
# `sed -i \⏎ 's/a/b/' f.sh` and `echo x > \⏎ f.sh` split the write across two lines.
# Join them. Joining can only merge lines, so it never hides a match.
SCAN=${SCAN//$'\\\n'/ }
if ! printf '%s' "$CMD" | grep -qE '(^|[^[:alnum:]_.-])(ln|mv)[[:space:]]'; then
  # Rebinding is judged on what the CURRENT shell runs (2026-11-01). A quoted-delimiter
  # heredoc body is data to it — `cat > $S/x.py <<'EOF'` with a Python `for` loop, or a
  # script body with its own `S=$1`, used to cancel the exemption for the outer `$S`.
  # Unquoted bodies stay in (`$((S=0))` there runs in this shell); a body read back
  # into this shell needs source/`.`/eval/read/mapfile OUTSIDE it, which still disables
  # the exemption below. With a CR, bash's delimiter isn't ours: no masking at all.
  REBIND_TXT="$CMD"
  if [[ "$CMD" != *$'\r'* ]]; then
    REBIND_TXT=$(mask_keep_outer "$(heredoc_body_mask quoted "$CMD")" "$CMD")
    # Hide `$` on quoted body lines of SCAN so the expansion below can't touch them
    # (those bodies are run, if at all, by another process with its own variables).
    # Restored right after the expansion. Masked before SCAN's join is irrelevant:
    # SCAN is already joined, so mask SCAN itself.
    _m=$(heredoc_body_mask quoted "$SCAN"); _i=0; _p=""
    while IFS= read -r _l || [[ -n "$_l" ]]; do
      [[ "${_m:_i:1}" == b ]] && _l=${_l//\$/$'\x1f'}
      _p+="$_l"$'\n'; _i=$((_i + 1))
    done <<< "$SCAN"
    SCAN=$_p
  fi
  REBIND_TXT=${REBIND_TXT//$'\\\n'/ }
  # Keywords are matched with quotes and backslashes removed: `\.`, `"."`, `r\ead`
  # and `so'urce'` are the same commands to bash. A keyword ends at any non-word
  # character (`read<<'EOF' S`). `.` as a command: after line start, ; & | ( { !, or
  # after a keyword that takes a command (if/while/then/time/command -p …).
  # (2026-11-01, from agy's review of this change: `if . /dev/stdin`, `\.`, `select`,
  # `read<<` were not seen.)
  KW_TXT=$(printf '%s' "$REBIND_TXT" | tr -d "'\"\\\\")
  KW_RE='(^|[^[:alnum:]_])(for|select|read|mapfile|readarray|declare|local|typeset|eval|getopts|unset|source|let|wait)([^[:alnum:]_.-]|$)|printf[[:space:]]+-v|(^|[;&|({!])[[:space:]]*\.([[:space:]]|$)|(^|[^[:alnum:]_])(if|elif|while|until|then|do|else|time|builtin|command|exec|coproc)[[:space:]]+(-[[:alnum:]]+[[:space:]]+)*\.([[:space:]]|$)|\(\('
  if ! printf '%s' "$KW_TXT" | grep -qE "$KW_RE" && ! heredoc_unsure "$REBIND_TXT"; then
    while IFS= read -r asg; do
      [[ -z "$asg" ]] && continue
      asg=${asg#export }
      var=${asg%%=*}; raw=${asg#*=}; val=$raw
      case "$raw" in
        \"*) [[ ${#raw} -gt 1 && "$raw" == *\" ]] || continue; val=${raw:1:${#raw}-2} ;;
        \'*) [[ ${#raw} -gt 1 && "$raw" == *\' ]] || continue; val=${raw:1:${#raw}-2} ;;
      esac
      [[ "$val" =~ ^/tmp/[A-Za-z0-9._/+@%:,=-]*$ ]] || continue
      n=$(printf '%s' "$REBIND_TXT" | grep -oE "(^|[^[:alnum:]_])${var}\+?=" | wc -l)
      [[ "$n" -eq 1 ]] || continue
      SCAN=${SCAN//"\${$var}"/$val}
      SCAN=${SCAN//"\$$var/"/$val/}
    # Statement-form assignments only: at line start or after ; & | (, and followed by
    # end of statement. grep -o is per line, so ^ and $ are line boundaries.
    done < <(printf '%s' "$REBIND_TXT" \
      | grep -oE "(^|[;&|(])[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=[^[:space:];&|)]+[[:space:]]*(;|&&|\|\||$)" \
      | sed -E 's/^[;&|(]?[[:space:]]*//; s/[[:space:]]*(;|&&|\|\|)?$//')
  fi
  SCAN=${SCAN//$'\x1f'/\$}
  # `cd /tmp/X && …` (2026-10-31): relative operands resolve under /tmp/X — but only
  # when the whole command is ONE `&&` chain (a failed cd then runs nothing), on one
  # line, with no second cd/pushd/popd and nothing that could run hidden code (eval,
  # source, `.`, sh -c, backticks, $( )). Anything else leaves relative operands as is.
  CD_TMP=""
  first=${SCAN%%$'\n'*}; rest=${SCAN#"$first"}
  if [[ -z "${rest//[$'\n']/}" && "$first" =~ ^[[:space:]]*cd[[:space:]]+(/tmp/[A-Za-z0-9._/+@%:,=-]+)[[:space:]]*\&\& ]]; then
    cdr=$(realpath -m -- "${BASH_REMATCH[1]}" 2>/dev/null) || cdr=""
    ncd=$(printf '%s' "$CMD" | grep -oE '(^|[^[:alnum:]_.-])(cd|pushd|popd)([[:space:]]|;|$)' | wc -l)
    sepbad=$(printf '%s' "$first" | awk '{
      q = ""; n = length($0); bad = 0
      for (i = 1; i <= n; i++) {
        c = substr($0, i, 1)
        if (q == "") {
          if (c == "\\") { i++; continue }
          if (c == "\047" || c == "\"") { q = c; continue }
          if (c == ";" || c == "`") bad = 1
          if (c == "$" && substr($0, i + 1, 1) == "(") bad = 1
          if (c == "|" && substr($0, i + 1, 1) == "|") bad = 1
          if (c == "&") {
            if (substr($0, i + 1, 1) == "&") { i++; continue }
            if (substr($0, i - 1, 1) == ">" || substr($0, i + 1, 1) == ">") continue
            bad = 1
          }
        } else if (q == "\"" && c == "\\") { i++ }
        else if (c == q) q = ""
      }
      print bad
    }')
    if [[ "$cdr" == /tmp/?* && "$cdr" != /tmp/premortem-cleared* && "$ncd" -eq 1 && "$sepbad" == 0 ]] \
       && ! printf '%s' "$CMD" | grep -qE '(^|[^[:alnum:]_])(eval|source|exec|bash|sh|zsh|dash|ksh)[[:space:]]|(^|[;&|(])[[:space:]]*\.[[:space:]]'; then
      CD_TMP="$cdr"
    fi
  fi
  OUT=""
  set -f
  while IFS= read -r line || [[ -n "$line" ]]; do
    newline=""
    for tok in $line; do
      keep="$tok"
      # Separators glued to the END of an operand stay as syntax (`$S/b.py;`); glued
      # anywhere else (`>/tmp/a;cp`) the token is left whole and stays scanned.
      core="$tok"; post=""
      if [[ "$core" =~ ^(.*[^\;\&\|\)])([\;\&\|\)]+)$ ]]; then
        core=${BASH_REMATCH[1]}; post=${BASH_REMATCH[2]}
      fi
      pre=${core%%/tmp/*}                     # redirect/quote prefix, e.g. `>` `2>` `"`
      t=""
      if [[ "$pre" != "$core" && "$pre" =~ ^[0-9]?\>{0,2}[\"\']?$ ]]; then
        t=${core:${#pre}}
      elif [[ -n "$CD_TMP" && "$core" =~ ^([0-9]?\>{0,2}[\"\']?)([A-Za-z0-9._+@%:,=][A-Za-z0-9._/+@%:,=-]*)[\"\']?$ \
              && "${BASH_REMATCH[2]}" == *[./]* ]]; then
        pre=${BASH_REMATCH[1]}; t="$CD_TMP/${BASH_REMATCH[2]}${core:${#BASH_REMATCH[1]}+${#BASH_REMATCH[2]}}"
      fi
      if [[ -n "$t" ]]; then
        q=""; [[ "$t" == *[\"\'] ]] && q=${t: -1}
        t=${t%\"}; t=${t%\'}
        if [[ "$t" =~ ^/tmp/[A-Za-z0-9._/+@%:,=-]+$ ]]; then
          r=$(realpath -m -- "$t" 2>/dev/null) || r=""
          if [[ "$r" == /tmp/?* && "$r" != /tmp/premortem-cleared* ]]; then
            # A placeholder, not nothing: a bare `>` would bind the next word.
            keep="${pre}__tmp__${q}${post}"
          fi
        fi
      fi
      newline+="${newline:+ }$keep"
    done
    OUT+="$newline"$'\n'
  done <<< "$SCAN"
  set +f
  SCAN="$OUT"
fi

# One command segment per line, for the sed check. A segment ends at a newline or an
# unquoted `;` or `&` (so `&&` too); a pipe does NOT end it, nor does `||`, so
# `find -name '*.sh' | xargs sed -i …` is one segment. Separators inside quotes are
# masked (`sed -i 's|a|b|' f.sh` stays whole) and so is the `&` of `2>&1` / `&>`.
# Quote state carries across lines and an unbalanced quote masks everything after it:
# every mistake here MERGES segments, which can add a match but never remove one.
# (2026-11-03) SED_RE and CP_RE stop at a `|` left in a segment, and a pipe left here
# wrongly would SPLIT a span (a false negative). So `|` is also masked when escaped
# (quoted or not) and inside $( ) <( ) >( ) or backticks, where `;` and `&` are
# masked too: `cp $(ls | head -1) scripts/y.sh` stays one span. Depth carries across
# lines, like quote state. Only unquoted parens are counted: `$(` opens, `)` closes.
SEGS=$(printf '%s\n' "$SCAN" | awk '
  BEGIN { q = ""; d = 0; bt = 0 }
  function esc(ch) { return ch == "|" ? "_" : ch }
  {
    out = ""; n = length($0)
    for (i = 1; i <= n; i++) {
      c = substr($0, i, 1)
      if (q == "") {
        if (c == "\\") { out = out c esc(substr($0, i + 1, 1)); i++; continue }
        p = substr($0, i - 1, 1)
        if (c == "(" && (p == "$" || p == "<" || p == ">")) d++
        else if (c == ")" && d > 0) d--
        else if (c == "`") bt = !bt
        if (c == "\047" || c == "\"") q = c
        else if ((d > 0 || bt) && (c == ";" || c == "&" || c == "|")) c = "_"
        else if (c == ";") c = "\n"
        else if (c == "&") {
          if (substr($0, i - 1, 1) == ">" || substr($0, i + 1, 1) == ">") c = "_"
          else c = "\n"
        }
      } else if (q == "\"" && c == "\\") { out = out c esc(substr($0, i + 1, 1)); i++; continue }
      else if (c == q) q = ""
      else if (c == ";" || c == "&" || c == "|") c = "_"
      out = out c
    }
    print out
  }')

HIT=0
echo "$SCAN" | grep -qE "$REDIR_RE" && HIT=1
[[ $HIT -eq 0 ]] && printf '%s\n' "$SEGS" | grep -E "$SED_RE" | grep -qE "$SURF_TOKEN_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$SCAN" | grep -qE "$PY_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$SCAN" | grep -qE "$PERL_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$SCAN" | grep -qE "$RUBY_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$SCAN" | grep -qE "$NODE_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$SCAN" | grep -qE "$AWK_RE" && HIT=1
[[ $HIT -eq 0 ]] && printf '%s\n' "$SEGS" | grep -qE "$CP_RE" && HIT=1

[[ $HIT -eq 0 ]] && exit 0

SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo "unknown")

# LOG must point at a directory that exists, so pick the root actually present.
LOG_ROOT=/opt/proj
for _cand in /opt/proj /c/opt/proj; do
  [ -d "$_cand" ] && { LOG_ROOT="$_cand"; break; }
done
LOG="${SURFACE_GUARD_LOG:-$LOG_ROOT/Uncle-J-s-Refinery/state/hook-blocks.log}"

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

# Collapse newlines/tabs BEFORE truncating: `head -c` cuts bytes, not lines, so a
# multi-line $CMD wrote N lines into the log and only the last carried `session=`.
# A block that cannot be found by searching for its own session is a block that
# cannot be audited — this guard's own entry on 2026-08-15 spilled across four
# physical lines with `session=` stranded on the fourth, and was reported as
# "fired but logged nothing". Same defect fixed in grep-guard.sh by PR #106.
# tr first, then truncate the now-single line. hook_log_append then strips any other
# control byte and the UTF-8 fragment `head -c` can leave, and rotates the log.
hook_log_append "$LOG" "$(date '+%Y-%m-%d %H:%M:%S') BLOCKED surface-write-guard bash-writes-surface cmd=$(printf '%s' "$CMD" | tr '\n\r\t' ' ' | head -c 200) session=$SESSION_ID"

jq -n '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "BLOCKED: Bash write to surface file detected.\n\nThis bypasses the Edit/Write tool guard. Use the Edit or Write Claude tools instead — they enforce the pre-mortem requirement.\n\nIf this is a legitimate authorized operation (e.g., bootstrap security fix), state so explicitly and confirm pre-mortem was completed for this task."
  }
}'
exit 0

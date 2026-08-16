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

HIT=0
echo "$CMD" | grep -qE "$REDIR_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$CMD" | grep -qE "$SED_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$CMD" | grep -qE "$PY_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$CMD" | grep -qE "$PERL_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$CMD" | grep -qE "$RUBY_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$CMD" | grep -qE "$NODE_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$CMD" | grep -qE "$AWK_RE" && HIT=1
[[ $HIT -eq 0 ]] && echo "$CMD" | grep -qE "$CP_RE" && HIT=1

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

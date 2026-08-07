#!/usr/bin/env bash
# uncle-j-force-rules — generic non-optional Stop-hook enforcement engine.
#
# Blocks turn-end until every rule in scripts/force-rules.d/*.sh is satisfied.
# A "rule" is a small script that inspects the CURRENT turn and exits 0 when its
# requirement is met, non-zero (printing a one-line reason) when it is not.
#
# To add a non-optional rule later: drop one executable-ish *.sh file into
# scripts/force-rules.d/. No settings.json edit required. See 10-terse-reply.sh
# for the contract.
#
# SAFETY INVARIANT: this hook can never brick a session. Every internal error
# path fails OPEN (exit 0 = allow stop), and a per-turn iteration cap forces the
# turn to end after MAX blocks even if a rule can never be satisfied.
set -u

INPUT=$(cat)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULES_DIR="$DIR/force-rules.d"
[ -d "$RULES_DIR" ] || exit 0                       # no rules → nothing to enforce
ls "$RULES_DIR"/*.sh >/dev/null 2>&1 || exit 0      # empty dir → allow

command -v jq >/dev/null 2>&1 || exit 0             # no jq → can't emit block JSON → allow

TRANSCRIPT=$(printf '%s' "$INPUT" | jq -r '.transcript_path // ""')
[ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ] || exit 0   # can't verify compliance → allow

# Documented loop backstop: Claude Code sets stop_hook_active=true on any Stop that is
# itself a continuation from a prior Stop-hook block. Honoring it means the hook blocks
# at most ONCE per stop-chain — a hard guarantee against an infinite loop, independent
# of the anchor logic below. (This is why enforcement is "one forced retry", not "block
# until complied": a Stop hook that never releases the turn is unrecoverable in-session.)
ACTIVE=$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false')
[ "$ACTIVE" = "true" ] && exit 0

# --- Current-turn slice: lines since the last GENUINE user prompt ------------
# type=user covers three things: real user prompts, tool_result lines, AND this hook's
# OWN block feedback (Claude Code injects the block reason as a user turn). Exclude the
# latter two. If we anchored to our own feedback, the anchor would advance past the
# model's compliance every iteration (perpetual re-block) and the cap key below would
# move with it (defeating the fail-open cap) — the brick bug this fix closes.
# The exclusion phrase MUST stay in sync with the block reason emitted at end of script.
LAST_USER=$(grep -n '"type":"user"' "$TRANSCRIPT" | grep -v 'tool_result' | grep -v 'non-optional rules are not yet satisfied' | tail -1 | cut -d: -f1)
SLICE=$(mktemp) || exit 0
trap 'rm -f "$SLICE"' EXIT
if [ -n "$LAST_USER" ]; then
  tail -n +"$LAST_USER" "$TRANSCRIPT" > "$SLICE" 2>/dev/null || cp "$TRANSCRIPT" "$SLICE"
else
  cp "$TRANSCRIPT" "$SLICE" 2>/dev/null || exit 0
fi

# --- Per-turn iteration cap (the anti-brick valve) ---------------------------
# Key is stable within one turn (transcript + last-user line) so repeated blocks
# for the SAME turn accumulate; it resets on the next user prompt.
MAX=5
KEY=$(printf '%s|%s' "$TRANSCRIPT" "${LAST_USER:-0}" | md5sum 2>/dev/null | cut -d' ' -f1)
CAP_DIR="${TMPDIR:-/tmp}/uncle-j-force-rules"
mkdir -p "$CAP_DIR" 2>/dev/null || true
CAP_FILE="$CAP_DIR/${KEY:-fallback}"
COUNT=$(cat "$CAP_FILE" 2>/dev/null || echo 0)
case "$COUNT" in ''|*[!0-9]*) COUNT=0 ;; esac
if [ "$COUNT" -ge "$MAX" ]; then
  echo "force-rules: iteration cap ($MAX) hit this turn; allowing stop (fail-open)" >&2
  rm -f "$CAP_FILE" 2>/dev/null || true
  exit 0
fi

# --- Evaluate every rule -----------------------------------------------------
UNMET=""
for rule in "$RULES_DIR"/*.sh; do
  [ -e "$rule" ] || continue
  reason=$(TURN_SLICE="$SLICE" TRANSCRIPT="$TRANSCRIPT" bash "$rule" 2>/dev/null)
  if [ "$?" -ne 0 ]; then
    UNMET="${UNMET}- ${reason:-$(basename "$rule")}
"
  fi
done

if [ -z "$UNMET" ]; then
  rm -f "$CAP_FILE" 2>/dev/null || true            # turn compliant → reset counter
  exit 0
fi

echo "$((COUNT + 1))" > "$CAP_FILE" 2>/dev/null || true
REASON="These non-optional rules are not yet satisfied for this turn — do them, then finish:
${UNMET}"
jq -cn --arg r "$REASON" '{decision:"block", reason:$r}'
exit 0

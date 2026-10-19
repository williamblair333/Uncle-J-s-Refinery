#!/usr/bin/env bash
# features/focus-check/focus-check.sh — weekly "estate vs. questions" scoreboard to Telegram.
#
# Bill's 2026-10-19 test: give immortality or Klarheit as many sessions as Uncle J gets,
# and see which one he reaches for first. This counts last week's Langfuse traces per
# project (via session-stats) and sends the score, so the reminder comes to him.
# The counts come from the 4-column table features/session-stats/stats.sh prints.
#
# Usage:
#   ./focus-check.sh [--dry-run]
#
# --dry-run Print the message instead of sending it.
#
# Exit codes: 0 sent (or printed), 1 stats or Telegram failure

set -euo pipefail

FOCUS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_ROOT="$(cd "$FOCUS_DIR/../.." && pwd)"
DRY_RUN=0

# Projects are matched on the folder name session-stats reports.
ESTATE="Uncle-J-s-Refinery gitea"
QUESTIONS="immortality aquarius hermetic_magic Klarheit free-energy neraas"

warn() { printf '    !!  %s\n' "$*" >&2; }

case "${1:-}" in
    --dry-run) DRY_RUN=1 ;;
    "") ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
esac

REPORT="$(bash "$STACK_ROOT/features/session-stats/stats.sh" --days 7)" \
    || { warn "session-stats failed; no scoreboard this week"; exit 1; }

MESSAGE="$(printf '%s\n' "$REPORT" | python3 -c '
import sys
estate, questions = sys.argv[1].split(), sys.argv[2].split()
counts = {}
for line in sys.stdin:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) == 4 and cells[2].isdigit():
        counts[cells[1]] = counts.get(cells[1], 0) + int(cells[2])
if not counts:
    sys.exit("no rows parsed from the session-stats table")
e = sum(counts.get(p, 0) for p in estate)
q = {p: counts[p] for p in questions if counts.get(p)}
q_total = sum(q.values())
detail = ", ".join(f"{p} {n}" for p, n in sorted(q.items(), key=lambda x: -x[1])) or "none"
verdict = "The questions won the week." if q_total >= e else "The estate won the week."
print("\n".join([
    "<b>Focus check</b> (last 7 days, Langfuse traces)",
    f"Estate (Uncle J): {e}",
    f"Questions: {q_total} ({detail})",
    verdict,
    "",
    "The test: give immortality or Klarheit as many sessions as Uncle J gets. Which did you reach for first?",
]))
' "$ESTATE" "$QUESTIONS")" || { warn "couldn't build the scoreboard"; exit 1; }

if [ "$DRY_RUN" -eq 1 ]; then
    printf '%s\n' "$MESSAGE"
    exit 0
fi

ENV_FILE="$STACK_ROOT/.env"
[ -f "$ENV_FILE" ] || { warn ".env missing; can't reach Telegram"; exit 1; }
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
# shellcheck source=../../lib/notify.sh
source "$STACK_ROOT/lib/notify.sh"
notify_send_text "$MESSAGE" || { warn "Telegram send failed"; exit 1; }
echo "focus-check: sent $(date -Is)"

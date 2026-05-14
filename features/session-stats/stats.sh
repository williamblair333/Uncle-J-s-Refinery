#!/usr/bin/env bash
# features/session-stats/stats.sh — weekly session efficiency reporter.
#
# Queries Langfuse for traces from the last 7 days and prints a markdown table:
#   | Date | Project | Traces | Tool calls | Tokens | Flag |
#
# Usage:
#   ./stats.sh [--days N] [--cron] [--dry-run]
#
# --cron    Write report to state/stats-weekly.md instead of stdout.
# --dry-run Print table header only; do not hit Langfuse API.
# --days N  Look back N days (default: 7).
#
# Exit codes: 0 success, 1 config/API error

set -euo pipefail

STATS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_ROOT="$(cd "$STATS_DIR/../.." && pwd)"
VENV_PY="$STACK_ROOT/.venv/bin/python"
STATE_DIR="$STACK_ROOT/state"
REPORT_FILE="$STATE_DIR/stats-weekly.md"
DAYS=7
CRON_MODE=0
DRY_RUN=0

step() { printf '\n==> %s\n' "$*" >&2; }
ok()   { printf '    OK  %s\n' "$*" >&2; }
warn() { printf '    !!  %s\n' "$*" >&2; }

while [ $# -gt 0 ]; do
    case "$1" in
        --days)    DAYS="${2:?}"; shift 2 ;;
        --cron)    CRON_MODE=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

# ── Dry-run: print header and exit ──────────────────────────────────────────
if [ "$DRY_RUN" -eq 1 ]; then
    printf '| Date | Project | Traces | Tool calls | Tokens | Flag |\n'
    printf '|------|---------|--------|------------|--------|------|\n'
    exit 0
fi

# ── Dependency check ─────────────────────────────────────────────────────────
[ -x "$VENV_PY" ] || { warn "Stack venv missing — run ./install.sh first"; exit 1; }
command -v curl >/dev/null 2>&1 || { warn "'curl' not on PATH"; exit 1; }

# ── Read Langfuse credentials ─────────────────────────────────────────────────
_get_setting() {
    "$VENV_PY" -c "import json,os; d=json.load(open(os.path.expanduser('~/.claude/settings.json'))); print(d.get('env',{}).get('$1',''))" 2>/dev/null
}
LANGFUSE_HOST="${LANGFUSE_HOST:-$(_get_setting LANGFUSE_HOST)}"
LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-$(_get_setting LANGFUSE_PUBLIC_KEY)}"
LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY:-$(_get_setting LANGFUSE_SECRET_KEY)}"

if [ -z "$LANGFUSE_PUBLIC_KEY" ] || [ -z "$LANGFUSE_SECRET_KEY" ] || [ -z "$LANGFUSE_HOST" ]; then
    warn "Langfuse credentials missing from ~/.claude/settings.json env block"
    warn "Fix: bash $STACK_ROOT/install-langfuse.sh"
    exit 1
fi

# ── Time window ───────────────────────────────────────────────────────────────
step "Querying Langfuse: last $DAYS days"
FROM_TS="$(date -u -d "${DAYS} days ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
           || date -u -v-${DAYS}d +%Y-%m-%dT%H:%M:%SZ)"
FROM_ENC="$("$VENV_PY" - "$FROM_TS" <<'PYEOF'
import urllib.parse, sys
print(urllib.parse.quote(sys.argv[1]))
PYEOF
)"

# ── Fetch traces ──────────────────────────────────────────────────────────────
TRACES_JSON="$(curl -sf --max-time 20 \
    -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
    "${LANGFUSE_HOST%/}/api/public/traces?limit=500&fromTimestamp=$FROM_ENC" 2>&1)"

if ! printf '%s' "$TRACES_JSON" | "$VENV_PY" -c "import sys,json; json.loads(sys.stdin.read())" >/dev/null 2>&1; then
    warn "Langfuse API returned non-JSON response"
    warn "Check: curl -u PK:SK ${LANGFUSE_HOST}/api/public/health"
    exit 1
fi

# ── Build report ──────────────────────────────────────────────────────────────
REPORT="$(TRACES_JSON="$TRACES_JSON" "$VENV_PY" - "$DAYS" <<'PYEOF'
import sys, json, collections, os

days = sys.argv[1]
raw = os.environ["TRACES_JSON"]
traces = json.loads(raw).get("data", [])

# Group by date + project
groups = collections.defaultdict(lambda: {"traces": 0, "tool_calls": 0, "tokens": 0})
for t in traces:
    date = (t.get("timestamp") or "")[:10]
    project = (t.get("metadata") or {}).get("project", "") or \
               (t.get("tags") or [""])[0] or "unknown"
    key = (date, project)
    groups[key]["traces"] += 1
    obs = t.get("observations") or []
    groups[key]["tool_calls"] += sum(1 for o in obs if o.get("type") == "SPAN")
    usage = t.get("usage") or {}
    groups[key]["tokens"] += (usage.get("totalTokens") or 0)

lines = [
    f"# Session Stats — last {days} days",
    f"Generated: {__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
    "",
    "| Date | Project | Traces | Tool calls | Tokens | Flag |",
    "|------|---------|--------|------------|--------|------|",
]
for (date, project) in sorted(groups.keys(), reverse=True):
    g = groups[(date, project)]
    flag = "⚠ high" if g["tokens"] > 40000 else "—"
    lines.append(
        f"| {date} | {project} | {g['traces']} | {g['tool_calls']} | {g['tokens']:,} | {flag} |"
    )

if not groups:
    lines.append("| — | no traces found | — | — | — | — |")

print("\n".join(lines))
PYEOF
)"

# ── Output ────────────────────────────────────────────────────────────────────
mkdir -p "$STATE_DIR"
if [ "$CRON_MODE" -eq 1 ]; then
    printf '%s\n' "$REPORT" > "$REPORT_FILE"
    ok "Report written to $REPORT_FILE"
    TRACE_COUNT="$(printf '%s' "$TRACES_JSON" | "$VENV_PY" -c \
        "import sys,json; print(len(json.loads(sys.stdin.read()).get('data',[])))" 2>/dev/null || echo '?')"
    printf '%s traces processed, report at %s\n' "$TRACE_COUNT" "$REPORT_FILE"
else
    printf '%s\n' "$REPORT"
fi

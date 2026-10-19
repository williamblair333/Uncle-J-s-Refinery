#!/usr/bin/env bash
# features/session-stats/stats.sh — weekly session efficiency reporter.
#
# Queries Langfuse for traces from the last 7 days and prints a markdown table:
#   | Date | Project | Traces | Observations |
#
# Tokens aren't reported: the Claude Code Langfuse hook records no token usage
# (every GENERATION carries usage 0), so a tokens column could only show a fake 0.
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
DREAM_OUTPUT_DIR="${DREAMING_OUTPUT_DIR:-$HOME/.claude/dreaming-output}"
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
    printf '| Date | Project | Traces | Observations |\n'
    printf '|------|---------|--------|--------------|\n'
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

# ── Fetch traces ──────────────────────────────────────────────────────────────
# Langfuse caps limit at 100 (a larger value is HTTP 400), so page through the window.
# fields=core,observations,metrics leaves out trace input/output: ~0.5 KB a trace instead of ~4 KB.
# The merged JSON goes to a temp file, never an env var: a week is ~400 KB, and Linux
# caps one env string at 128 KB.
step "Querying Langfuse: last $DAYS days"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
TRACES_FILE="$TMP_DIR/traces.json"
LANGFUSE_AUTH="$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
"$VENV_PY" - "$LANGFUSE_HOST" "$DAYS" "$TRACES_FILE" <<'PYEOF' || exit 1
import base64, datetime, json, os, sys, urllib.error, urllib.parse, urllib.request

host, days, out = sys.argv[1].rstrip("/"), int(sys.argv[2]), sys.argv[3]
MAX_PAGES = 50
since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
         ).strftime("%Y-%m-%dT%H:%M:%SZ")
auth = "Basic " + base64.b64encode(os.environ["LANGFUSE_AUTH"].encode()).decode()
traces, page, total_pages = [], 1, 1
while page <= min(total_pages, MAX_PAGES):
    q = urllib.parse.urlencode({"limit": 100, "page": page, "fromTimestamp": since,
                                "fields": "core,observations,metrics"})
    req = urllib.request.Request(f"{host}/api/public/traces?{q}", headers={"Authorization": auth})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.load(r)
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:300]
        print(f"    !!  Langfuse HTTP {e.code} on page {page}: {msg}", file=sys.stderr)
        sys.exit(1)
    except (urllib.error.URLError, ValueError, OSError) as e:
        print(f"    !!  Langfuse request failed on page {page}: {e}", file=sys.stderr)
        sys.exit(1)
    traces += body.get("data", [])
    total_pages = (body.get("meta") or {}).get("totalPages", 1)
    page += 1
json.dump({"data": traces, "truncated": total_pages > MAX_PAGES}, open(out, "w"))
PYEOF

# ── Build report ──────────────────────────────────────────────────────────────
REPORT="$("$VENV_PY" - "$DAYS" "$TRACES_FILE" <<'PYEOF'
import sys, json, collections, datetime

days, path = sys.argv[1], sys.argv[2]
doc = json.load(open(path))
traces = doc.get("data", [])

# Group by date + project. A trace lists its observations as ids: the turn span,
# one span per tool call and the model response, so this counts activity, not tools.
groups = collections.defaultdict(lambda: {"traces": 0, "observations": 0})
for t in traces:
    date = (t.get("timestamp") or "")[:10]
    project = (t.get("metadata") or {}).get("project", "") or \
               (t.get("tags") or [""])[0] or "unknown"
    key = (date, project)
    groups[key]["traces"] += 1
    groups[key]["observations"] += len(t.get("observations") or [])

lines = [
    f"# Session Stats — last {days} days",
    f"Generated: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
    "",
    "| Date | Project | Traces | Observations |",
    "|------|---------|--------|--------------|",
]
for (date, project) in sorted(groups.keys(), reverse=True):
    g = groups[(date, project)]
    lines.append(f"| {date} | {project} | {g['traces']} | {g['observations']} |")

if not groups:
    lines.append("| — | no traces found | — | — |")
lines += ["", f"{len(traces)} traces. Tokens: not recorded (the Langfuse hook logs no usage)."]
if doc.get("truncated"):
    lines.append("Truncated: only the newest 5000 traces were read.")

print("\n".join(lines))
PYEOF
)"

# ── Output ────────────────────────────────────────────────────────────────────
mkdir -p "$STATE_DIR"
if [ "$CRON_MODE" -eq 1 ]; then
    mkdir -p "$DREAM_OUTPUT_DIR"
    DREAM_FILE="$DREAM_OUTPUT_DIR/stats-$(date +%Y-%m-%d).md"
    printf '%s\n' "$REPORT" > "$DREAM_FILE"
    printf '%s\n' "$REPORT" > "$REPORT_FILE"
    ok "Report written to $DREAM_FILE (dreaming input)"
    ok "Report written to $REPORT_FILE (human reference)"
else
    printf '%s\n' "$REPORT"
fi

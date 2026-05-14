#!/usr/bin/env bash
# features/dreaming/dream.sh — Dream synthesizer for Uncle J's Refinery.
#
# Queries Langfuse for traces since the last run, invokes the
# dream-synthesizer skill via claude -p, writes playbooks to MemPalace,
# and optionally appends proven playbooks to ~/.claude/CLAUDE.md.
#
# Usage:
#   ./dream.sh [--since <ISO8601>] [--dry-run]
#
# Exit codes: 0 success/skip, 1 config error, 2 synthesis error

set -euo pipefail

DREAM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_ROOT="$(cd "$DREAM_DIR/../.." && pwd)"
VENV_PY="$STACK_ROOT/.venv/bin/python"
MEMPALACE="$STACK_ROOT/.venv/bin/mempalace"
SKILL_FILE="$DREAM_DIR/skills/dream-synthesizer/SKILL.md"
STATE_DIR="$STACK_ROOT/state"
LAST_RUN_FILE="$STATE_DIR/dreaming-last-run.txt"
LOG_FILE="$STATE_DIR/dreaming.log"
ENV_FILE="$STATE_DIR/dreaming.env"
DRY_RUN=0
SINCE=""

step() { printf '\n==> %s\n' "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }
log_entry() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG_FILE"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --since)   SINCE="${2:?}"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

# Load env overrides
[ -f "$ENV_FILE" ] && source "$ENV_FILE" || true
DREAMING_OUTPUT_DIR="${DREAMING_OUTPUT_DIR:-$HOME/.claude/dreaming-output}"

# ── Dependency checks ────────────────────────────────────────────────────────
[ -x "$VENV_PY" ]    || { warn "Stack venv missing — run ./install.sh first"; exit 1; }
[ -x "$MEMPALACE" ]  || { warn "mempalace binary missing — run ./install.sh first"; exit 1; }
[ -f "$SKILL_FILE" ] || { warn "dream-synthesizer skill missing — run features/dreaming/install.sh"; exit 1; }
command -v claude >/dev/null 2>&1 || { warn "'claude' CLI not on PATH"; exit 1; }
command -v curl   >/dev/null 2>&1 || { warn "'curl' not on PATH"; exit 1; }

# ── Read Langfuse credentials ─────────────────────────────────────────────────
_get_setting() {
    "$VENV_PY" -c "import json,os; d=json.load(open(os.path.expanduser('~/.claude/settings.json'))); print(d.get('env',{}).get('$1',''))" 2>/dev/null
}
LANGFUSE_HOST="${LANGFUSE_HOST:-$(_get_setting LANGFUSE_HOST)}"
LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-$(_get_setting LANGFUSE_PUBLIC_KEY)}"
LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY:-$(_get_setting LANGFUSE_SECRET_KEY)}"

if [ -z "$LANGFUSE_PUBLIC_KEY" ] || [ -z "$LANGFUSE_SECRET_KEY" ] || [ -z "$LANGFUSE_HOST" ]; then
    warn "Langfuse credentials missing from ~/.claude/settings.json env block"
    warn "Run install-langfuse.sh to configure them"
    exit 1
fi

# ── Determine time window ────────────────────────────────────────────────────
mkdir -p "$STATE_DIR"
if [ -n "$SINCE" ]; then
    FROM_TS="$SINCE"
else
    if [ -f "$LAST_RUN_FILE" ]; then
        FROM_TS="$(cat "$LAST_RUN_FILE")"
    else
        FROM_TS="$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
                   || date -u -v-24H +%Y-%m-%dT%H:%M:%SZ)"
    fi
fi
NOW_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ── Query Langfuse ────────────────────────────────────────────────────────────
step "Querying Langfuse traces since $FROM_TS"
FROM_ENC="$("$VENV_PY" - "$FROM_TS" <<'PYEOF'
import urllib.parse, sys
print(urllib.parse.quote(sys.argv[1]))
PYEOF
)"
TRACES_JSON="$(curl -s --max-time 15 \
    -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
    "${LANGFUSE_HOST%/}/api/public/traces?limit=100&fromTimestamp=$FROM_ENC" 2>&1)"

TRACE_COUNT="$(printf '%s' "$TRACES_JSON" | "$VENV_PY" -c \
    "import sys,json; d=json.loads(sys.stdin.read()); print(len(d.get('data',[])))" 2>/dev/null || echo 0)"
ok "Found $TRACE_COUNT traces"

if [ "$TRACE_COUNT" -eq 0 ]; then
    ok "No new traces — skipping synthesis"
    printf '%s\n' "$NOW_TS" > "$LAST_RUN_FILE"
    log_entry "skip: no traces since $FROM_TS"
    exit 0
fi

# ── Format traces for synthesizer ────────────────────────────────────────────
step "Formatting $TRACE_COUNT trace(s) for synthesis"
FORMATTED="$(printf '%s' "$TRACES_JSON" | "$VENV_PY" - <<'PYEOF'
import sys, json
data = json.loads(sys.stdin.read()).get("data", [])
lines = []
for t in data[:30]:
    session  = t.get("sessionId", "?")
    ts       = (t.get("timestamp") or "")[:10]
    inp      = str(t.get("input",  "") or "")[:300]
    out      = str(t.get("output", "") or "")[:300]
    obs      = t.get("observations", []) or []
    tools    = list({o.get("name","") for o in obs if o.get("type") == "SPAN"})[:8]
    lines.append(f"--- Session {session} ({ts}) ---")
    lines.append(f"Task: {inp}")
    lines.append(f"Result: {out}")
    if tools:
        lines.append(f"Tools used: {', '.join(tools)}")
    lines.append("")
print("\n".join(lines))
PYEOF
)"

# ── Invoke dream-synthesizer ──────────────────────────────────────────────────
step "Invoking dream-synthesizer"
SKILL_CONTENT="$(cat "$SKILL_FILE")"
TMP="$(mktemp --suffix=.md)"
printf '<skill>\n%s\n</skill>\n\n<session-traces>\n%s\n</session-traces>\n' \
    "$SKILL_CONTENT" "$FORMATTED" > "$TMP"

if [ "$DRY_RUN" -eq 1 ]; then
    ok "[dry-run] would invoke: claude -p @$TMP --dangerously-skip-permissions"
    SYNTHESIS="## Recurring Mistakes

(dry-run placeholder)

## Proven Playbooks

(dry-run placeholder)"
else
    SYNTHESIS="$(claude -p "@$TMP" --dangerously-skip-permissions 2>&1 || true)"
fi
rm -f "$TMP"

if [ -z "$SYNTHESIS" ]; then
    warn "Synthesis returned empty output"
    log_entry "fail: empty synthesis output ($TRACE_COUNT traces)"
    exit 2
fi

# ── Write output to MemPalace ─────────────────────────────────────────────────
step "Writing to MemPalace via mine"
mkdir -p "$DREAMING_OUTPUT_DIR"
OUTPUT_FILE="$DREAMING_OUTPUT_DIR/dream-$(date +%Y-%m-%d).md"

{
    printf '# Dreaming output — %s\n\n' "$NOW_TS"
    printf '%s\n' "$SYNTHESIS"
} > "$OUTPUT_FILE"

if [ "$DRY_RUN" -eq 0 ]; then
    "$MEMPALACE" mine "$DREAMING_OUTPUT_DIR" --wing "dreaming" 2>/dev/null \
        && ok "MemPalace updated" \
        || warn "MemPalace mine failed (non-fatal — output still written to $OUTPUT_FILE)"
else
    ok "[dry-run] would mine: $DREAMING_OUTPUT_DIR"
fi

# ── Append proven playbooks to CLAUDE.md (idempotent) ────────────────────────
CLAUDE_MD="$HOME/.claude/CLAUDE.md"
if [ -f "$CLAUDE_MD" ] && [ "$DRY_RUN" -eq 0 ]; then
    step "Updating ~/.claude/CLAUDE.md § Dreaming Notes"
    PLAYBOOKS="$(printf '%s' "$SYNTHESIS" | awk '/^## Proven Playbooks/{found=1} found{print}' | head -30)"
    if [ -n "$PLAYBOOKS" ]; then
        NOW_TS_ESCAPED="$NOW_TS"
        PLAYBOOKS_ESCAPED="$PLAYBOOKS"
        "$VENV_PY" - <<PYEOF
import pathlib
p = pathlib.Path('$CLAUDE_MD')
content = p.read_text()
marker = '\n## Dreaming Notes (auto-generated)'
if marker in content:
    content = content[:content.index(marker)]
content = content.rstrip() + '\n\n## Dreaming Notes (auto-generated)\n\n'
content += '<!-- Last updated: $NOW_TS_ESCAPED -->\n\n'
import sys, os
playbooks = os.environ.get('PLAYBOOKS_ESCAPED', '')
content += playbooks + '\n'
p.write_text(content)
print('  OK  CLAUDE.md updated')
PYEOF
    fi
fi

# ── Update last-run timestamp ─────────────────────────────────────────────────
printf '%s\n' "$NOW_TS" > "$LAST_RUN_FILE"
log_entry "ok: $TRACE_COUNT traces processed -> $OUTPUT_FILE"

step "Dreaming run complete"
ok "Traces processed : $TRACE_COUNT"
ok "Output           : $OUTPUT_FILE"
ok "Last run         : $LAST_RUN_FILE"

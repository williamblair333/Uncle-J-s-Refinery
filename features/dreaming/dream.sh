#!/usr/bin/env bash
# features/dreaming/dream.sh — Dream synthesizer for Uncle J's Refinery.
#
# Queries Langfuse for traces since the last run, invokes the
# dream-synthesizer skill via claude -p, writes playbooks to the memweave store,
# and optionally appends proven playbooks to ~/.claude/CLAUDE.md.
#
# Usage:
#   ./dream.sh [--since <ISO8601>] [--dry-run]
#
# Exit codes: 0 success/skip, 1 config error, 2 synthesis error

set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

DREAM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_ROOT="$(cd "$DREAM_DIR/../.." && pwd)"
VENV_PY="$STACK_ROOT/.venv/bin/python"
MEMWEAVE_STORE="$HOME/.uncle-j-memory/memory"
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
TRACES_TMP="$(mktemp)"
printf '%s' "$TRACES_JSON" > "$TRACES_TMP"
FORMATTED="$("$VENV_PY" - "$TRACES_TMP" <<'PYEOF'
import sys, json
with open(sys.argv[1]) as f:
    data = json.load(f).get("data", [])
lines = []
for t in data[:30]:
    session  = t.get("sessionId", "?")
    ts       = (t.get("timestamp") or "")[:10]
    inp      = str(t.get("input",  "") or "")[:300]
    out      = str(t.get("output", "") or "")[:300]
    obs      = t.get("observations", []) or []
    tools    = list({o.get("name","") for o in obs if isinstance(o, dict) and o.get("type") == "SPAN"})[:8]
    lines.append(f"--- Session {session} ({ts}) ---")
    lines.append(f"Task: {inp}")
    lines.append(f"Result: {out}")
    if tools:
        lines.append(f"Tools used: {', '.join(tools)}")
    lines.append("")
print("\n".join(lines))
PYEOF
)"
rm -f "$TRACES_TMP"

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

# ── URL hold-filter: quarantine URL-bearing playbooks before mine/CLAUDE.md ───
# This is a locator filter, not a truth filter. It holds playbooks that cite a
# URL for human review; it cannot judge relevance. "URL-free" != "verified."
step "Filtering synthesis for URL-bearing playbook entries"
PENDING_DIR="$STATE_DIR/dream-pending-review"
HELD_COUNT=0
TOTAL_PLAYBOOKS=0
_ORIG_SYNTHESIS="$SYNTHESIS"
_SYNTH_TMP="$(mktemp --suffix=.txt)"
printf '%s' "$SYNTHESIS" > "$_SYNTH_TMP"
FILTER_RESULT="$("$VENV_PY" - "$_SYNTH_TMP" "$NOW_TS" "$PENDING_DIR" "$DRY_RUN" <<'PYEOF'
import re, sys, pathlib

url_re = re.compile(r'https?://\S+')
synth_file, now_ts, pending_dir_str, dry_run = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
synthesis_raw = pathlib.Path(synth_file).read_text()
is_dry_run = dry_run == '1'

try:
    lines = synthesis_raw.split('\n')
    in_playbooks = False
    clean_lines = []
    held_entries = []
    total_playbook_entries = 0

    for line in lines:
        if re.match(r'^## Proven Playbooks', line):
            in_playbooks = True
            clean_lines.append(line)
            continue
        if in_playbooks and re.match(r'^## ', line):
            in_playbooks = False
        if in_playbooks and line.startswith('- '):
            total_playbook_entries += 1
            if url_re.search(line):
                held_entries.append(line)
                continue
        clean_lines.append(line)

    held_count = len(held_entries)
    if held_entries and not is_dry_run:
        pending_dir = pathlib.Path(pending_dir_str)
        pending_dir.mkdir(parents=True, exist_ok=True)
        ts_safe = now_ts.replace(':', '').replace(' ', 'T')[:15]
        held_file = pending_dir / f'held-{ts_safe}.md'
        held_content = (
            f'# Held dream playbooks — {now_ts}\n\n'
            'These entries contain URLs and require human verification before promotion.\n'
            'To promote: copy entries into ~/.uncle-j-memory/memory/ for the next memweave sync.\n'
            'To reject: delete this file.\n\n'
            '## Held Playbooks\n\n'
            + '\n'.join(held_entries) + '\n'
        )
        held_file.write_text(held_content)

    print(held_count)
    print(total_playbook_entries)
    sys.stdout.write('\n'.join(clean_lines))

except Exception as e:
    sys.stderr.write(f'URL filter error: {e}\n')
    print(0)
    print(-1)
    sys.stdout.write(synthesis_raw)
PYEOF
)"
rm -f "$_SYNTH_TMP"
HELD_COUNT="$(printf '%s\n' "$FILTER_RESULT" | head -1)"
TOTAL_PLAYBOOKS="$(printf '%s\n' "$FILTER_RESULT" | sed -n '2p')"
SYNTHESIS="$(printf '%s\n' "$FILTER_RESULT" | tail -n +3)"
if ! printf '%s' "${HELD_COUNT:-x}" | grep -qE '^[0-9]+$'; then
    warn "URL filter produced unexpected output — proceeding without filtering"
    HELD_COUNT=0; TOTAL_PLAYBOOKS=-1; SYNTHESIS="$_ORIG_SYNTHESIS"
fi
unset _ORIG_SYNTHESIS
[ "${HELD_COUNT:-0}" -gt 0 ] \
    && ok "Held ${HELD_COUNT} URL-bearing playbook(s) → $PENDING_DIR" \
    || ok "No URL-bearing playbooks detected"

# ── Promote dreaming output into the memweave memory store ────────────────────
# Copy the synthesis into the cross-project memweave store (~/.uncle-j-memory/memory);
# the nightly `sync_memory.sh --all` cron then embeds it. (Replaces the old mempalace mine.)
step "Promoting dreaming output to the memweave store"
mkdir -p "$DREAMING_OUTPUT_DIR"
OUTPUT_FILE="$DREAMING_OUTPUT_DIR/dream-$(date +%Y-%m-%d).md"

{
    printf '# Dreaming output — %s\n\n' "$NOW_TS"
    printf '%s\n' "$SYNTHESIS"
} > "$OUTPUT_FILE"

if [ "$DRY_RUN" -eq 0 ]; then
    if mkdir -p "$MEMWEAVE_STORE" && cp "$OUTPUT_FILE" "$MEMWEAVE_STORE/dream-$(date +%Y-%m-%d).md"; then
        ok "dreaming output promoted to memweave store (embedded on next sync)"
    else
        warn "memweave promotion failed (non-fatal — output still written to $OUTPUT_FILE)"
    fi
else
    ok "[dry-run] would copy dream output into $MEMWEAVE_STORE"
fi

# ── Append proven playbooks to CLAUDE.md (idempotent) ────────────────────────
CLAUDE_MD="$HOME/.claude/CLAUDE.md"
if [ -f "$CLAUDE_MD" ] && [ "$DRY_RUN" -eq 0 ]; then
    if [ "${HELD_COUNT:-0}" -gt 0 ] && [ "${TOTAL_PLAYBOOKS:-0}" -gt 0 ] && \
       [ "${HELD_COUNT:-0}" -ge "${TOTAL_PLAYBOOKS:-0}" ]; then
        warn "All ${HELD_COUNT} playbook(s) held for URL review — CLAUDE.md Dreaming Notes unchanged"
    else
        step "Updating ~/.claude/CLAUDE.md § Dreaming Notes"
        PLAYBOOKS="$(printf '%s' "$SYNTHESIS" | awk '/^## Proven Playbooks/{found=1} found{print}' | head -30)"
        if [ -n "$PLAYBOOKS" ]; then
            PLAYBOOKS_TMP="$(mktemp --suffix=.txt)"
            printf '%s\n' "$PLAYBOOKS" > "$PLAYBOOKS_TMP"
            "$VENV_PY" - "$CLAUDE_MD" "$PLAYBOOKS_TMP" "$NOW_TS" <<'PYEOF'
import pathlib, sys
claude_md_path, playbooks_path, now_ts = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(claude_md_path)
content = p.read_text()
marker = '\n## Dreaming Notes (auto-generated)'
if marker in content:
    content = content[:content.index(marker)]
content = content.rstrip() + '\n\n## Dreaming Notes (auto-generated)\n\n'
content += f'<!-- Last updated: {now_ts} -->\n\n'
content += pathlib.Path(playbooks_path).read_text()
p.write_text(content)
print('  OK  CLAUDE.md updated')
PYEOF
            rm -f "$PLAYBOOKS_TMP"
        fi
    fi
fi

# ── Update last-run timestamp ─────────────────────────────────────────────────
printf '%s\n' "$NOW_TS" > "$LAST_RUN_FILE"
log_entry "ok: $TRACE_COUNT traces processed -> $OUTPUT_FILE"

# FYI notification — skip if no traces or dry-run (nothing interesting to report)
if [[ "$DRY_RUN" -eq 0 && "${TRACE_COUNT:-0}" -gt 0 ]]; then
    # Load Telegram credentials from .env (gitignored, main worktree). Sourced
    # late so it cannot shadow already-resolved Langfuse vars. notify-telegram.sh
    # expands ${TELEGRAM_BOT_TOKEN} at source time, so the caller must guard.
    set -a; [ -f "$STACK_ROOT/.env" ] && source "$STACK_ROOT/.env"; set +a
    if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
        _DREAM_MSG="🌙 Dream run: ${TRACE_COUNT} trace(s) processed → playbooks promoted to the memweave store."
        [ "${HELD_COUNT:-0}" -gt 0 ] && \
            _DREAM_MSG="${_DREAM_MSG} ${HELD_COUNT} playbook(s) held for URL review → $PENDING_DIR"
        source "$STACK_ROOT/lib/notify.sh" 2>/dev/null \
            && notify_send_text "$_DREAM_MSG" \
            || true
    else
        warn "Telegram token absent — skipping dream notification"
    fi
fi

step "Dreaming run complete"
ok "Traces processed : $TRACE_COUNT"
ok "Output           : $OUTPUT_FILE"
ok "Last run         : $LAST_RUN_FILE"

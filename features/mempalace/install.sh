#!/usr/bin/env bash
# features/mempalace/install.sh
# Bootstrap and maintain MemPalace for Uncle J's Refinery.
#
# Install actions:
#   1. Run `mempalace init` on the project (idempotent)
#   2. Register a Stop hook — mines ~/.claude/projects/ --mode convos after every session
#   3. Register a daily 3am cron — mines the project repo for code content
#
# Usage:
#   bash features/mempalace/install.sh [--uninstall]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SETTINGS="$PROJ_ROOT/.claude/settings.json"
MEMPALACE_BIN="$PROJ_ROOT/.venv/bin/mempalace"
CLAUDE_PROJECTS="$HOME/.claude/projects"
MARKER_STOP="uncle-j-mempalace-convos"
MARKER_CRON="uncle-j-mempalace-mine"

source "$PROJ_ROOT/lib/feature-helpers.sh"

step() { printf '\n==> %s\n' "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }

# ── helpers ───────────────────────────────────────────────────────────────────

_remove_stop_hook() {
  python3 - "$SETTINGS" "$MARKER_STOP" << 'PYEOF'
import sys, json
path, marker = sys.argv[1], sys.argv[2]
with open(path) as f:
    cfg = json.load(f)
hooks = cfg.setdefault("hooks", {})
groups = hooks.get("Stop", [])
new_groups = []
for g in groups:
    filtered = [h for h in g.get("hooks", []) if marker not in h.get("command", "")]
    if filtered:
        new_groups.append(dict(g, hooks=filtered))
if new_groups:
    hooks["Stop"] = new_groups
elif "Stop" in hooks:
    del hooks["Stop"]
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PYEOF
}

# ── uninstall ─────────────────────────────────────────────────────────────────

if [[ "${1:-}" == "--uninstall" ]]; then
  step "Removing Stop hook ($MARKER_STOP)"
  _remove_stop_hook
  ok "Stop hook removed"
  step "Removing cron job ($MARKER_CRON)"
  remove_cron "$MARKER_CRON"
  ok "Cron removed"
  step "Done"
  exit 0
fi

# ── dependency check ──────────────────────────────────────────────────────────

step "Checking dependencies"
if [[ ! -x "$MEMPALACE_BIN" ]]; then
  warn "mempalace not found at $MEMPALACE_BIN"
  warn "Run: cd $PROJ_ROOT && python3 -m venv .venv && .venv/bin/pip install mempalace"
  exit 1
fi
ok "mempalace at $MEMPALACE_BIN"

if [[ ! -d "$CLAUDE_PROJECTS" ]]; then
  warn "~/.claude/projects/ not found — no Claude Code sessions to mine yet."
  warn "Continuing anyway; the Stop hook will mine once sessions exist."
fi

# ── init project ──────────────────────────────────────────────────────────────

step "Initializing MemPalace for $PROJ_ROOT"
"$MEMPALACE_BIN" init "$PROJ_ROOT" 2>&1 | sed 's/^/    /' || true
ok "init complete (idempotent)"

# ── mine project code ─────────────────────────────────────────────────────────

step "Mining project repo (initial code index)"
"$MEMPALACE_BIN" mine "$PROJ_ROOT" 2>&1 | sed 's/^/    /' || true
ok "project code indexed"

# ── mine existing sessions ────────────────────────────────────────────────────

if [[ -d "$CLAUDE_PROJECTS" ]]; then
  step "Mining existing Claude Code sessions (one-time backfill)"
  "$MEMPALACE_BIN" mine "$CLAUDE_PROJECTS" --mode convos 2>&1 | sed 's/^/    /' || true
  ok "sessions indexed"
fi

# ── Stop hook — mine convos after every session ───────────────────────────────

step "Registering Stop hook in $SETTINGS"
_remove_stop_hook  # idempotent

STOP_CMD="${MEMPALACE_BIN} mine ${CLAUDE_PROJECTS} --mode convos < /dev/null  # ${MARKER_STOP}"

python3 - "$SETTINGS" "$STOP_CMD" << 'PYEOF'
import sys, json
path, cmd = sys.argv[1], sys.argv[2]
with open(path) as f:
    cfg = json.load(f)
hooks = cfg.setdefault("hooks", {})
hooks.setdefault("Stop", []).append({
    "hooks": [{"type": "command", "command": cmd, "async": True}]
})
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PYEOF
ok "Stop hook registered (async, fires after every session)"

# ── cron — mine project code daily ───────────────────────────────────────────

step "Registering daily cron (3am)"
CRON_ENTRY="0 3 * * * ${MEMPALACE_BIN} mine ${PROJ_ROOT} >> ${PROJ_ROOT}/state/mempalace-mine.log 2>&1"
install_cron "$MARKER_CRON" "$CRON_ENTRY"
ok "Cron installed: 0 3 * * *"

# ── summary ───────────────────────────────────────────────────────────────────

step "Done"
printf '\n'
printf '  Project indexed:  %s\n' "$PROJ_ROOT"
printf '  Sessions indexed: %s\n' "$CLAUDE_PROJECTS"
printf '  Stop hook:        mines convos after every session\n'
printf '  Daily cron:       3am — re-mines project code\n'
printf '\n'
printf '  To uninstall: bash %s/install.sh --uninstall\n' "$SCRIPT_DIR"
printf '\n'

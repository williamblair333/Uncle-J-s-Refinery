#!/usr/bin/env bash
# features/auto-skill/install.sh
# Installs (or removes) the Uncle J auto-skill Stop hook in .claude/settings.json.
# Usage: ./install.sh [--uninstall]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SETTINGS="$PROJ_ROOT/.claude/settings.json"
NOTIFY_SCRIPT="$PROJ_ROOT/scripts/skill-suggest.sh"
MARKER="uncle-j-auto-skill"

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
step() { printf '\n==> %s\n' "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }

# ---------------------------------------------------------------------------
# JSON helper — remove any Stop hook whose command contains MARKER
# ---------------------------------------------------------------------------
_remove_hook() {
  python3 - "$SETTINGS" "$MARKER" << 'PYEOF'
import sys, json

settings_path = sys.argv[1]
marker = sys.argv[2]

with open(settings_path, "r") as fh:
    cfg = json.load(fh)

hooks = cfg.setdefault("hooks", {})
stop_groups = hooks.get("Stop", [])

new_stop = []
for group in stop_groups:
    inner = group.get("hooks", [])
    filtered = [h for h in inner if marker not in h.get("command", "")]
    if filtered:
        group = dict(group)
        group["hooks"] = filtered
        new_stop.append(group)
    # drop group entirely if all hooks were the marker

if new_stop:
    hooks["Stop"] = new_stop
elif "Stop" in hooks:
    del hooks["Stop"]

with open(settings_path, "w") as fh:
    json.dump(cfg, fh, indent=2)
    fh.write("\n")
PYEOF
}

# ---------------------------------------------------------------------------
# --uninstall
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--uninstall" ]]; then
  step "Removing Stop hook from $SETTINGS"
  _remove_hook
  ok "Hook removed (marker: $MARKER)"
  exit 0
fi

# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------
step "Checking dependencies"
for dep in claude python3 bash; do
  if command -v "$dep" &>/dev/null; then
    ok "$dep found"
  else
    warn "$dep not found — please install it and retry"
    exit 1
  fi
done

# ---------------------------------------------------------------------------
# Verify skill-suggest.sh exists
# ---------------------------------------------------------------------------
step "Verifying $NOTIFY_SCRIPT"
if [[ ! -f "$NOTIFY_SCRIPT" ]]; then
  warn "scripts/skill-suggest.sh not found at $NOTIFY_SCRIPT"
  warn "Run Task C1 first to create it."
  exit 1
fi
ok "skill-suggest.sh found"

# ---------------------------------------------------------------------------
# Idempotent hook injection
# ---------------------------------------------------------------------------
step "Updating Stop hook in $SETTINGS"

# Remove any existing entry first (idempotency)
_remove_hook

# Append fresh entry
HOOK_COMMAND="bash ${NOTIFY_SCRIPT}  # ${MARKER}"

python3 - "$SETTINGS" "$HOOK_COMMAND" << 'PYEOF'
import sys, json

settings_path = sys.argv[1]
hook_command  = sys.argv[2]

with open(settings_path, "r") as fh:
    cfg = json.load(fh)

hooks = cfg.setdefault("hooks", {})
stop_groups = hooks.setdefault("Stop", [])

new_group = {
    "hooks": [
        {
            "type": "command",
            "command": hook_command,
            "async": True
        }
    ]
}
stop_groups.append(new_group)

with open(settings_path, "w") as fh:
    json.dump(cfg, fh, indent=2)
    fh.write("\n")
PYEOF

ok "Stop hook registered"

# ---------------------------------------------------------------------------
# Send test Telegram message
# ---------------------------------------------------------------------------
step "Sending test Telegram message"

# Load .env for telegram credentials
ENV_FILE="$PROJ_ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  # Try the main worktree (git common dir parent)
  GIT_COMMON="$(git -C "$PROJ_ROOT" rev-parse --git-common-dir 2>/dev/null || true)"
  if [[ -n "$GIT_COMMON" ]]; then
    MAIN_ROOT="$(cd "$GIT_COMMON/.." && pwd)"
    [[ -f "$MAIN_ROOT/.env" ]] && ENV_FILE="$MAIN_ROOT/.env"
  fi
fi

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=../../.env
  source "$ENV_FILE"
  set +a

  if [[ -f "$PROJ_ROOT/lib/notify.sh" ]]; then
    source "$PROJ_ROOT/lib/notify.sh"
    notify_send_text "🧠 Uncle J skill-suggest <b>active</b>. A skill draft will be auto-generated after sessions that demonstrate reusable workflows."
    ok "Test message sent"
  fi
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
printf '\n'
printf '==> Done!\n'
printf '\n'
printf '    The Stop hook is now active. After each Claude Code session that\n'
printf '    demonstrates reusable workflows, a skill draft will be generated\n'
printf '    and saved to ~/.claude/skills/drafts/\n'
printf '\n'
printf '    To uninstall:\n'
printf '      bash %s/install.sh --uninstall\n' "$SCRIPT_DIR"
printf '\n'

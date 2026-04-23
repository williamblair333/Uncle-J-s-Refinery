#!/usr/bin/env bash
# features/telegram-notify/install.sh
# Installs (or removes) the Uncle J session-notify Stop hook in .claude/settings.json.
# Usage: ./install.sh [--uninstall]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SETTINGS="$PROJ_ROOT/.claude/settings.json"
NOTIFY_SCRIPT="$PROJ_ROOT/scripts/session-notify.sh"
MARKER="uncle-j-session-notify"

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
for dep in curl python3 bash; do
  if command -v "$dep" &>/dev/null; then
    ok "$dep found"
  else
    warn "$dep not found — please install it and retry"
    exit 1
  fi
done

# ---------------------------------------------------------------------------
# Verify .env has TELEGRAM_BOT_TOKEN
# .env is gitignored and lives only in the main worktree; fall back there
# if the current worktree doesn't have its own copy.
# ---------------------------------------------------------------------------
step "Verifying TELEGRAM_BOT_TOKEN in .env"
ENV_FILE="$PROJ_ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  # Try the main worktree (git common dir parent)
  GIT_COMMON="$(git -C "$PROJ_ROOT" rev-parse --git-common-dir 2>/dev/null || true)"
  if [[ -n "$GIT_COMMON" ]]; then
    MAIN_ROOT="$(cd "$GIT_COMMON/.." && pwd)"
    [[ -f "$MAIN_ROOT/.env" ]] && ENV_FILE="$MAIN_ROOT/.env"
  fi
fi
if [[ ! -f "$ENV_FILE" ]]; then
  warn ".env not found (checked $PROJ_ROOT/.env and main worktree)"
  warn "Create it and add: TELEGRAM_BOT_TOKEN=<token>  TELEGRAM_CHAT_ID=<id>"
  exit 1
fi

if ! grep -q "^TELEGRAM_BOT_TOKEN=" "$ENV_FILE" 2>/dev/null; then
  warn "TELEGRAM_BOT_TOKEN is not set in $ENV_FILE"
  warn "Add: TELEGRAM_BOT_TOKEN=<your-bot-token>"
  exit 1
fi
ok "TELEGRAM_BOT_TOKEN present"

# ---------------------------------------------------------------------------
# Verify session-notify.sh exists
# ---------------------------------------------------------------------------
step "Verifying $NOTIFY_SCRIPT"
if [[ ! -f "$NOTIFY_SCRIPT" ]]; then
  warn "scripts/session-notify.sh not found at $NOTIFY_SCRIPT"
  warn "Run Task A1 first to create it."
  exit 1
fi
ok "session-notify.sh found"

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

# Load .env
set -a
# shellcheck source=../../.env
source "$ENV_FILE"
set +a

source "$PROJ_ROOT/lib/notify.sh"
notify_send_text "🔔 Uncle J session notifications <b>active</b>. You'll receive a summary after each Claude session."

ok "Test message sent"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
printf '\n'
printf '==> Done!\n'
printf '\n'
printf '    The Stop hook is now active. After each Claude Code session,\n'
printf '    a Telegram summary will be dispatched automatically.\n'
printf '\n'
printf '    To uninstall:\n'
printf '      bash %s/install.sh --uninstall\n' "$SCRIPT_DIR"
printf '\n'

#!/usr/bin/env bash
# features/session-stats/install.sh — register weekly stats cron and install /stats command
# Usage: ./install.sh [--uninstall]

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$STACK_ROOT/lib/feature-helpers.sh"

MARKER="uncle-j-session-stats"
STATS_SCRIPT="$SCRIPT_DIR/stats.sh"
CMD_SRC="$SCRIPT_DIR/stats.md"
CMD_DST="${HOME}/.claude/commands/stats.md"
STATE_DIR="$STACK_ROOT/state"
ENV_FILE="$STATE_DIR/session-stats.env"

step() { printf '\n==> %s\n' "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }

if [ "${1:-}" = "--uninstall" ]; then
    step "Removing session-stats cron entry"
    remove_cron "$MARKER"
    ok "cron entry removed (command left in place)"
    exit 0
fi

chmod +x "$STATS_SCRIPT"

step "Installing /stats slash command"
mkdir -p "$(dirname "$CMD_DST")"
cp "$CMD_SRC" "$CMD_DST"
ok "installed to $CMD_DST"

step "Writing session-stats env defaults"
mkdir -p "$STATE_DIR"
SCHEDULE="${STATS_CRON_SCHEDULE:-0 8 * * 0}"
write_env_var "$ENV_FILE" "STATS_CRON_SCHEDULE" "$SCHEDULE"
ok "env file: $ENV_FILE"

step "Registering cron entry (schedule: $SCHEDULE — every Sunday 8 AM)"
CRON_CMD="$SCHEDULE bash \"$STATS_SCRIPT\" --cron >> \"$STATE_DIR/stats.log\" 2>&1"
install_cron "$MARKER" "$CRON_CMD"
ok "cron registered"

step "Session stats installed"
printf '\n'
printf '  Run on demand:  bash %s\n' "$STATS_SCRIPT"
printf '  Inside Claude:  /stats\n'
printf '  Weekly report:  %s\n' "$STATE_DIR/stats-weekly.md"
printf '  Disable:        bash %s --uninstall\n' "$SCRIPT_DIR/install.sh"
printf '  Schedule env:   STATS_CRON_SCHEDULE in %s\n\n' "$ENV_FILE"

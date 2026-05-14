#!/usr/bin/env bash
# features/dreaming/install.sh — register dreaming cron and install skill/command
# Usage: ./install.sh [--uninstall]

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$STACK_ROOT/lib/feature-helpers.sh"

MARKER="uncle-j-dreaming"
DREAM_SCRIPT="$SCRIPT_DIR/dream.sh"
SKILL_SRC="$SCRIPT_DIR/skills/dream-synthesizer"
SKILL_DST="${HOME}/.claude/skills/dream-synthesizer"
CMD_SRC="$SCRIPT_DIR/dream.md"
CMD_DST="${HOME}/.claude/commands/dream.md"
STATE_DIR="$STACK_ROOT/state"
ENV_FILE="$STATE_DIR/dreaming.env"

step() { printf '\n==> %s\n' "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }

if [ "${1:-}" = "--uninstall" ]; then
    step "Removing dreaming cron entry"
    remove_cron "$MARKER"
    ok "cron entry removed (skill and command left in place)"
    exit 0
fi

# Make dream.sh executable
chmod +x "$DREAM_SCRIPT"

# Install skill
step "Installing dream-synthesizer skill"
mkdir -p "$SKILL_DST"
cp -r "$SKILL_SRC/." "$SKILL_DST/"
ok "installed to $SKILL_DST"

# Install /dream slash command
step "Installing /dream slash command"
mkdir -p "$(dirname "$CMD_DST")"
cp "$CMD_SRC" "$CMD_DST"
ok "installed to $CMD_DST"

# Write env defaults
step "Writing dreaming env defaults"
mkdir -p "$STATE_DIR"
SCHEDULE="${DREAMING_CRON_SCHEDULE:-0 2 * * *}"
write_env_var "$ENV_FILE" "DREAMING_CRON_SCHEDULE" "$SCHEDULE"
write_env_var "$ENV_FILE" "DREAMING_ENABLED" "1"
ok "env file: $ENV_FILE"

# Register cron
step "Registering cron entry (schedule: $SCHEDULE)"
CRON_CMD="$SCHEDULE bash \"$DREAM_SCRIPT\" >> \"$STATE_DIR/dreaming.log\" 2>&1"
install_cron "$MARKER" "$CRON_CMD"
ok "cron registered"

step "Dreaming feature installed"
printf '\n'
printf '  Run on demand:  bash %s\n' "$DREAM_SCRIPT"
printf '  Inside Claude:  /dream\n'
printf '  Disable:        bash %s --uninstall\n' "$SCRIPT_DIR/install.sh"
printf '  Schedule env:   DREAMING_CRON_SCHEDULE in %s\n\n' "$ENV_FILE"

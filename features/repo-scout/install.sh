#!/usr/bin/env bash
# Install the repo scout's nightly cron (Linux/Mac). Telegram must already be set up
# (features/telegram-gateway and features/stack-alerts write TELEGRAM_* to .env).
# Usage:
#   bash features/repo-scout/install.sh             # install (default 04:15)
#   SCOUT_TIME=05:30 bash features/repo-scout/install.sh
#   bash features/repo-scout/install.sh --uninstall

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

source "$PROJ_ROOT/lib/feature-helpers.sh"

step()  { printf '\n==> %s\n' "$*"; }
ok()    { printf '    OK  %s\n' "$*"; }
warn()  { printf '    !!  %s\n' "$*" >&2; }

CRON_MARKER="uncle-j-repo-scout"

if [[ "${1:-}" == "--uninstall" ]]; then
  step "Uninstalling repo scout"
  remove_cron "$CRON_MARKER"
  ok "Cron job removed. Answers in scout/ and state in state/scout-* are kept."
  exit 0
fi

step "Checking dependencies"
for cmd in gh python3; do
  command -v "$cmd" &>/dev/null || { warn "$cmd not found — install it and re-run."; exit 1; }
  ok "$cmd"
done
gh auth status &>/dev/null || { warn "gh is not logged in — run: gh auth login"; exit 1; }
ok "gh logged in"
CLAUDE_BIN=$(command -v claude 2>/dev/null || true)
[[ -n "$CLAUDE_BIN" ]] || { warn "claude CLI not found on PATH."; exit 1; }
ok "claude at $CLAUDE_BIN"
grep -q '^TELEGRAM_BOT_TOKEN=' "$PROJ_ROOT/.env" 2>/dev/null \
  || { warn "No Telegram config in .env — run features/stack-alerts/install.sh first."; exit 1; }
ok "Telegram configured"

# Default 04:15: after the 02:30 memweave sync and 03:00 auto-maintain, done before 07:00.
SCOUT_TIME="${SCOUT_TIME:-04:15}"
HOUR=$((10#${SCOUT_TIME%%:*}))
MIN=$((10#${SCOUT_TIME##*:}))

step "Installing cron job"
# PATH must be explicit in cron — its default is /usr/bin:/bin only, which has no gh.
CRON_PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
ENTRY="${MIN} ${HOUR} * * * PATH=${CRON_PATH} CLAUDE_BIN=${CLAUDE_BIN} python3 ${PROJ_ROOT}/scripts/scout/run.py run >> ${PROJ_ROOT}/state/scout.log 2>&1"
mkdir -p "$PROJ_ROOT/state"
install_cron "$CRON_MARKER" "$ENTRY"
ok "Nightly at ${SCOUT_TIME}"

step "Done"
echo ""
echo "  Discovery stays off until scout/map.md says reviewed: true;"
echo "  repos in scout/inbox.md are scouted from tonight."
echo "  Run by hand:   just scout --dry-run"
echo "  Status:        just scout-status"
echo "  Uninstall:     bash features/repo-scout/install.sh --uninstall"
echo "  Log:           $PROJ_ROOT/state/scout.log"

#!/usr/bin/env bash
# Install the boot-time cron catch-up (Linux). Cron skips any job whose time passes
# while the machine is off; this @reboot entry runs those jobs once each after boot.
# See scripts/cron_catchup.py for which jobs qualify.
# Usage:
#   bash features/cron-catchup/install.sh
#   bash features/cron-catchup/install.sh --uninstall

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

source "$PROJ_ROOT/lib/feature-helpers.sh"

step()  { printf '\n==> %s\n' "$*"; }
ok()    { printf '    OK  %s\n' "$*"; }
warn()  { printf '    !!  %s\n' "$*" >&2; }

CRON_MARKER="uncle-j-cron-catchup"

if [[ "${1:-}" == "--uninstall" ]]; then
  step "Uninstalling cron catch-up"
  remove_cron "$CRON_MARKER"
  ok "Cron entry removed. state/cron-catchup.* are kept."
  exit 0
fi

step "Checking dependencies"
command -v python3 &>/dev/null || { warn "python3 not found."; exit 1; }
ok "python3"
journalctl --list-boots -o json 2>/dev/null | python3 -c 'import json,sys; json.load(sys.stdin)' \
  || { warn "journalctl --list-boots -o json gives no boot list (needs systemd >= 251, persistent journal)."; exit 1; }
ok "journal lists boots as JSON"

step "Installing cron entry"
# PATH must be explicit in cron — its default is /usr/bin:/bin only, which has no gh.
# The sleep lets the network, Docker and Ollama come up before the jobs need them;
# nice/ionice keep the catch-up from slowing the session Bill opens at boot.
CRON_PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
ENTRY="@reboot sleep 120 && PATH=${CRON_PATH} nice -n 10 ionice -c3 python3 ${PROJ_ROOT}/scripts/cron_catchup.py >> ${PROJ_ROOT}/state/cron-catchup.log 2>&1"
mkdir -p "$PROJ_ROOT/state"
install_cron "$CRON_MARKER" "$ENTRY"
ok "Runs 2 min after each boot"

step "Done"
echo ""
echo "  Preview:   python3 $PROJ_ROOT/scripts/cron_catchup.py --dry-run"
echo "  Log:       $PROJ_ROOT/state/cron-catchup.log"
echo "  Uninstall: bash features/cron-catchup/install.sh --uninstall"

#!/usr/bin/env bash
# Stop hook — vendor GUI steps must be looked up this turn (or labelled "from memory") and
# must come with the CLI way. Logic lives in scripts/ui_steps_scan.py (this file is installed
# as a symlink, so resolve it). Fails open: a missing or broken script never blocks a stop.
HERE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
python3 "$HERE/../../scripts/ui_steps_scan.py" 2>/dev/null || exit 0

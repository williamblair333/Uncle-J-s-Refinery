#!/usr/bin/env bash
# Stop hook — a turn that leaves proof to chance gets one forced look at forcing the event.
# Logic lives in scripts/chance_check.py (this file is installed as a symlink, so resolve it).
# Fails open: a missing or broken script, or a busy local model, never blocks a stop.
HERE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
python3 "$HERE/../../scripts/chance_check.py" 2>/dev/null || exit 0

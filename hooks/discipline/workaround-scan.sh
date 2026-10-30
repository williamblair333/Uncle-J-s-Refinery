#!/usr/bin/env bash
# Stop hook — a turn that worked around a block must fix the cause or file it.
# Logic lives in scripts/workaround_scan.py (this file is installed as a symlink, so resolve it).
# Fails open: a missing or broken script never blocks a stop.
HERE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
python3 "$HERE/../../scripts/workaround_scan.py" 2>/dev/null || exit 0

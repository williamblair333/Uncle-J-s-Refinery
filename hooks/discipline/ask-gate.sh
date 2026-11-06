#!/usr/bin/env bash
# Stop hook — a turn that ends asking permission for work it could just do gets one forced retry.
# Logic lives in scripts/ask_gate.py (this file is installed as a symlink, so resolve it).
# Fails open: a missing or broken script never blocks a stop.
HERE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
python3 "$HERE/../../scripts/ask_gate.py" 2>/dev/null || exit 0

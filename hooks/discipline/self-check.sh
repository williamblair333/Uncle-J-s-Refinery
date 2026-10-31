#!/usr/bin/env bash
# Stop hook — verify factual claims before ending a substantive turn.
# Logic lives in scripts/self_check.py (this file is installed as a symlink, so resolve it).
# Fails open: a missing or broken script never blocks a stop.
HERE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
python3 "$HERE/../../scripts/self_check.py" 2>/dev/null || exit 0

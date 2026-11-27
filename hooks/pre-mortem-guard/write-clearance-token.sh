#!/usr/bin/env bash
# Write a pre-mortem clearance token. Called by the /pre-mortem skill as its
# final step, after the analysis is complete and STATUS is CLEAR.
#
# This script was previously not in version control at all: it existed only as
# ~/.claude/hooks/pre-mortem-guard/write-clearance-token.sh on one machine, while
# hooks/discipline/edit-surface-guard.sh and the pre-mortem SKILL.md both
# referenced it by that path. Porting the stack to a second host therefore
# installed a guard that blocks surface edits with no way to clear it. Keeping
# the writer beside the guard that consumes it is what stops that recurring.
#
# Token format: {"ts": <epoch>, "status": "PRE-MORTEM-COMPLETE"} — expires 2h.
# Must be a regular file (the guard rejects symlinks).
#
# Since 2026-11-27 the analysis itself is the second argument, and check_clears.py
# refuses it when a RECOVERY / DATA INTEGRITY / SECURITY CLEAR, or any CLEAR that
# says "never"/"always"/"cannot", cites nothing checked. A rhcsa-lab pre-mortem
# cleared RECOVERY with "the ISO is never modified", unchecked; the rollback it
# named deleted the ISO. Fails closed: no python3, no file, no token.
#
# Usage: write-clearance-token.sh <token-path> <analysis-file>
set -euo pipefail

TOKEN="${1:-}"
ANALYSIS="${2:-}"
USAGE="usage: write-clearance-token.sh <token-path> <analysis-file>
  <analysis-file>: the full pre-mortem text (dimension blocks + STATUS), saved with the Write tool"
if [ -z "$TOKEN" ] || [ -z "$ANALYSIS" ]; then echo "$USAGE" >&2; exit 2; fi

case "$(basename "$TOKEN")" in
    premortem-cleared-*) ;;
    *) echo "refusing: token name must be premortem-cleared-<session-id>" >&2; exit 2 ;;
esac

DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
if ! python3 -I "$DIR/check_clears.py" "$ANALYSIS"; then
    echo "no token written: fix the CLEARs above (or turn them into findings) and rerun" >&2
    exit 1
fi

rm -f "$TOKEN"
printf '{"ts": %s, "status": "PRE-MORTEM-COMPLETE"}\n' "$(date +%s)" > "$TOKEN"
chmod 600 "$TOKEN" 2>/dev/null || true
echo "clearance token written: $TOKEN"

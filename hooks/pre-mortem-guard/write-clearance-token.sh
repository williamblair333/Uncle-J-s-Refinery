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
# Usage: write-clearance-token.sh <token-path>
set -euo pipefail

TOKEN="${1:-}"
[ -n "$TOKEN" ] || { echo "usage: write-clearance-token.sh <token-path>" >&2; exit 2; }

case "$(basename "$TOKEN")" in
    premortem-cleared-*) ;;
    *) echo "refusing: token name must be premortem-cleared-<session-id>" >&2; exit 2 ;;
esac

rm -f "$TOKEN"
printf '{"ts": %s, "status": "PRE-MORTEM-COMPLETE"}\n' "$(date +%s)" > "$TOKEN"
chmod 600 "$TOKEN" 2>/dev/null || true
echo "clearance token written: $TOKEN"

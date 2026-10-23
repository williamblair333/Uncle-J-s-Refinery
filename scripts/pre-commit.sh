#!/usr/bin/env bash
# pre-commit.sh — the git pre-commit hook (install.sh symlinks .git/hooks/pre-commit here).
# Runs every commit gate in turn; any one failing blocks the commit.
#   1. session-end-check.sh — mandatory docs staged with code
#   2. jscrub/precommit-scan.sh — no invisible Unicode in staged text (report-only)
set -uo pipefail

# Resolve through the .git/hooks symlink to this file's real directory.
SELF="$(readlink -f "${BASH_SOURCE[0]}")"
DIR="$(dirname "$SELF")"

rc=0
bash "$DIR/session-end-check.sh" "$@" || rc=1
bash "$DIR/jscrub/precommit-scan.sh" || rc=1
exit "$rc"

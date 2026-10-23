#!/usr/bin/env bash
# audit-repo.sh — read-only invisible-Unicode sweep of this repo's tracked text files.
#
# Runs `jscrub check-vendor` (vendored engine unmodified? no network, no checkout),
# then a live-positive canary, then `jscrub audit` over git-tracked source and docs.
# Never writes to the repo: `clean`, `--in-place` and `--follow-symlinks` are
# deliberately not wired into automation.
#
# Tracked files only, so the gitignored review/ and reviewed/ third-party clones
# in the main checkout are never swept.
#
# Exit codes are jscrub's: 0 clean, 1 hits found, 2 something could not be
# scanned. Treat both 1 and 2 as failure. A failed canary exits 3.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
# JSCRUB_BIN lets the tests swap in a broken detector to prove the canary fires.
JSCRUB="${JSCRUB_BIN:-scripts/jscrub/jscrub}"
# shellcheck source=pathspec.sh
source scripts/jscrub/pathspec.sh

"$JSCRUB" check-vendor

# Live-positive canary. The repo's own fixtures are excluded, so a clean audit
# below can't tell "no hits" from "detector broken". Build a file that MUST hit
# (a zero-width space, written as bytes so no tracked file carries one) and
# require exit 1. Lives in a temp dir; nothing in the repo is touched.
CANARY_DIR="$(mktemp -d "${TMPDIR:-/tmp}/jscrub-canary.XXXXXX")"
trap 'rm -f -- "$CANARY_DIR/canary.md"; rmdir -- "$CANARY_DIR" 2>/dev/null || true' EXIT
printf 'canary\xe2\x80\x8bword\n' > "$CANARY_DIR/canary.md"
canary_rc=0
"$JSCRUB" audit --quiet "$CANARY_DIR/canary.md" >/dev/null 2>&1 || canary_rc=$?
if [ "$canary_rc" -ne 1 ]; then
    echo "FATAL: jscrub canary not detected (exit $canary_rc, want 1) — the detector is broken" >&2
    exit 3
fi
echo "canary: zero-width space detected (detector live)"

mapfile -d '' FILES < <(git ls-files -z -- "${JSCRUB_PATHSPEC[@]}")

[ "${#FILES[@]}" -gt 0 ] || { echo "FATAL: git ls-files returned nothing to audit" >&2; exit 2; }
"$JSCRUB" audit --quiet "${FILES[@]}"

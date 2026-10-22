#!/usr/bin/env bash
# audit-repo.sh — read-only invisible-Unicode sweep of this repo's tracked text files.
#
# Runs `jscrub check-vendor` (vendored engine unmodified? no network, no checkout)
# then `jscrub audit` over git-tracked source and docs. Never writes: `clean`,
# `--in-place` and `--follow-symlinks` are deliberately not wired into automation.
#
# Tracked files only, so the gitignored review/ and reviewed/ third-party clones
# in the main checkout are never swept.
#
# Exit codes are jscrub's: 0 clean, 1 hits found, 2 something could not be
# scanned. Treat both 1 and 2 as failure.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
JSCRUB="scripts/jscrub/jscrub"

"$JSCRUB" check-vendor

# Intentional fixtures, excluded by path:
#   tests/test_tg_security.py — sanitizer tests carry ZWSP and RLO on purpose.
#   docs/superpowers/plans/2026-05-20-telegram-gateway-security-hardening.md —
#     the sanitizer's regex is quoted with a literal NUL, so jscrub refuses it
#     as binary (exit 2).
mapfile -d '' FILES < <(git ls-files -z -- \
    '*.py' '*.sh' '*.md' '*.toml' '*.yml' '*.yaml' '*.json' '*.txt' justfile \
    ':!tests/test_tg_security.py' \
    ':!docs/superpowers/plans/2026-05-20-telegram-gateway-security-hardening.md')

[ "${#FILES[@]}" -gt 0 ] || { echo "FATAL: git ls-files returned nothing to audit" >&2; exit 2; }
exec "$JSCRUB" audit --quiet "${FILES[@]}"

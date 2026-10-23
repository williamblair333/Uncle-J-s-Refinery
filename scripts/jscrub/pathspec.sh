# shellcheck shell=bash
# Which tracked files the jscrub gates sweep. Sourced by audit-repo.sh (whole repo)
# and precommit-scan.sh (staged files), so the two can't drift apart.
#
# Intentional fixtures, excluded by path:
#   tests/test_tg_security.py — sanitizer tests carry ZWSP and RLO on purpose.
#   docs/superpowers/plans/2026-05-20-telegram-gateway-security-hardening.md —
#     the sanitizer's regex is quoted with a literal NUL, so jscrub refuses it
#     as binary (exit 2).
# shellcheck disable=SC2034  # used by the sourcing script
JSCRUB_PATHSPEC=(
    '*.py' '*.sh' '*.md' '*.toml' '*.yml' '*.yaml' '*.json' '*.txt' justfile
    ':!tests/test_tg_security.py'
    ':!docs/superpowers/plans/2026-05-20-telegram-gateway-security-hardening.md'
)

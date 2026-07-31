#!/usr/bin/env bash
# PostToolUse(Write|Edit) hook: auto-checkpoint commit, but only when the edit
# happened inside THIS repo.
#
# Replaces the previous inline hook, which compared `git rev-parse --show-toplevel`
# against the literal string "/opt/proj/Uncle-J-s-Refinery". On Windows Git Bash
# that call returns "C:/opt/proj/Uncle-J-s-Refinery", so the guard never matched
# and checkpointing silently never fired.
#
# The repo root is now derived from this script's own location, so the guard is
# correct on Linux and Windows without hardcoding either path.
set -uo pipefail

SELF_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CWD_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$CWD_ROOT" ] || exit 0

# Compare by filesystem identity, not by string. Under MSYS the same directory has
# several spellings -- git says "C:/opt/proj/X", `pwd` says "/c/opt/proj/X", and
# mount aliases can rewrite others again (C:/Users/<u>/AppData/Local/Temp -> /tmp).
# `-ef` compares device+inode, so every spelling of one directory matches.
[ "$CWD_ROOT" -ef "$SELF_ROOT" ] || exit 0

cd "$SELF_ROOT" || exit 0
git add -u 2>/dev/null || exit 0
git diff --cached --quiet && exit 0
git commit -m "chk: $(date +%H:%M:%S)" -q 2>/dev/null || true
exit 0

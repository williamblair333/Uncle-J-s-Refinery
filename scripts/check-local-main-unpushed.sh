#!/usr/bin/env bash
# check-local-main-unpushed.sh — warn when LOCAL main has commits the remote lacks.
#
# WHY THIS EXISTS
# The 03:00 auto-maintain agent commits to local main and never pushes. Policy forbids
# pushing main directly (branch -> PR -> merge), so those commits sit there and ride
# into whatever branch is cut next. `git log HEAD..origin/main` cannot see it: that
# asks "is the remote ahead of me", never "am I ahead of the remote", and
# origin/main itself is only as fresh as the last fetch. `git ls-remote` is the only
# authority on the remote ref (see check-origin-main-regression.sh).
#
# Detection only. This script never pushes.
#
# Usage:  check-local-main-unpushed.sh [repo_root]
# Exit:   0 = in sync / behind / check skipped, 1 = local main has unpushed commits.
# Output: one line. "AHEAD <n> ..." on exit 1; "OK ..." or "SKIP ..." otherwise.

set -uo pipefail

REPO_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BRANCH="${UNPUSHED_MAIN_BRANCH:-main}"
REMOTE_NAME="${UNPUSHED_MAIN_REMOTE:-origin}"

if ! git -C "$REPO_ROOT" remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
    echo "SKIP no-$REMOTE_NAME-remote"
    exit 0
fi

LOCAL=$(git -C "$REPO_ROOT" rev-parse --verify -q "refs/heads/$BRANCH" 2>/dev/null)
if [[ -z "$LOCAL" ]]; then
    echo "SKIP no-local-$BRANCH"
    exit 0
fi

# Never prompt: runs from SessionStart and cron with no tty.
SSH_BATCH="${GIT_SSH_COMMAND:-ssh} -o BatchMode=yes -o ConnectTimeout=5"
if command -v timeout >/dev/null 2>&1; then
    REMOTE=$(GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="$SSH_BATCH" \
        timeout 8 git -C "$REPO_ROOT" ls-remote "$REMOTE_NAME" "refs/heads/$BRANCH" 2>/dev/null | cut -f1)
else
    REMOTE=$(GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="$SSH_BATCH" \
        git -C "$REPO_ROOT" ls-remote "$REMOTE_NAME" "refs/heads/$BRANCH" 2>/dev/null | cut -f1)
fi

# Offline, auth failure, timeout: say nothing rather than guess.
if [[ -z "$REMOTE" ]]; then
    echo "SKIP ls-remote-empty (offline, auth failure, or timeout)"
    exit 0
fi

if [[ "$LOCAL" == "$REMOTE" ]]; then
    echo "OK $BRANCH in sync with $REMOTE_NAME (${LOCAL:0:7})"
    exit 0
fi

if git -C "$REPO_ROOT" cat-file -e "${REMOTE}^{commit}" 2>/dev/null; then
    AHEAD=$(git -C "$REPO_ROOT" rev-list --count "$REMOTE..$LOCAL" 2>/dev/null || echo 0)
    BEHIND=$(git -C "$REPO_ROOT" rev-list --count "$LOCAL..$REMOTE" 2>/dev/null || echo 0)
else
    # Remote tip not fetched yet. Count what no remote-tracking ref has: an
    # approximation, but it never reports a pushed commit as unpushed.
    AHEAD=$(git -C "$REPO_ROOT" rev-list --count "$LOCAL" --not --remotes="$REMOTE_NAME" 2>/dev/null || echo 0)
    BEHIND="?"
fi

if [[ "${AHEAD:-0}" -gt 0 ]]; then
    echo "AHEAD $AHEAD local $BRANCH has $AHEAD commit(s) $REMOTE_NAME/$BRANCH lacks (behind $BEHIND; local ${LOCAL:0:7}, remote ${REMOTE:0:7})"
    exit 1
fi

echo "OK $BRANCH behind $REMOTE_NAME by $BEHIND, nothing unpushed"
exit 0

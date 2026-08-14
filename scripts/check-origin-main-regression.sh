#!/usr/bin/env bash
# check-origin-main-regression.sh — detect a non-fast-forward regression of origin/main.
#
# WHY THIS EXISTS
# origin/main was force-reset to an older commit FIVE times (2026-08-04, 08-07 x2,
# 08-09, 08-14), silently destroying merged PRs #100-#105. Every detection to date was
# accidental and days late, because both instruments people reach for lie:
#   * `gh pr list`    still reports force-pushed-away PRs as MERGED
#   * `git branch -a` lists remote-tracking refs for branches the remote no longer has
# `git ls-remote` is the only authority on remote ref state.
#
# The GitHub ruleset protect-main-no-force-push (id 20854165) now rejects the push at
# the server. This script verifies the OUTCOME independently, so detection survives the
# ruleset being disabled for an intentional rewrite, or absent on another clone.
#
# THE SIGNAL is not "local is ahead of remote" -- that is normal during unpushed work.
# It is "the current origin/main is NOT a descendant of the last one we recorded".
#
# Usage:  check-origin-main-regression.sh [repo_root]
# Exit:   0 = no regression (or check skipped), 1 = regression detected.
# Prints to stdout only when something needs a human; silence is the healthy case.

set -uo pipefail

REPO_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# state/origin-main-last-seen.sha is EVIDENCE, NOT CACHE. Deleting it silently disarms
# this detector: the next run adopts whatever the remote then says -- including a
# regressed SHA -- as the new baseline. It sits beside jcodemunch-last-indexed.sha,
# which genuinely is disposable; these two are not the same kind of file.
SEEN="${ORIGIN_MAIN_SEEN_FILE:-$REPO_ROOT/state/origin-main-last-seen.sha}"
REGLOG="${ORIGIN_MAIN_REG_LOG:-$REPO_ROOT/state/origin-main-regressions.log}"
BRANCH="${ORIGIN_MAIN_BRANCH:-main}"

ts()   { date '+%Y-%m-%d %H:%M:%S'; }
note() { printf '%s  %s\n' "$(ts)" "$*" >> "$REGLOG" 2>/dev/null || true; }

mkdir -p "$(dirname "$SEEN")" "$(dirname "$REGLOG")" 2>/dev/null || true

# Atomic stamp write. Concurrent session starts are routine here -- three were observed
# on 2026-08-13 -- and a torn SHA would cost a comparison.
stamp() {
    local tmp="$SEEN.tmp.$$"
    printf '%s\n' "$1" > "$tmp" 2>/dev/null && mv -f "$tmp" "$SEEN" 2>/dev/null \
        || rm -f "$tmp" 2>/dev/null || true
}

if ! git -C "$REPO_ROOT" remote get-url origin >/dev/null 2>&1; then
    echo "SKIP no-origin-remote"
    exit 0
fi

# Never prompt: this runs from a SessionStart hook with no tty, so a locked ssh-agent or
# an expired credential must fail fast rather than block session start. Appending to any
# existing GIT_SSH_COMMAND preserves a custom key/config while still forcing batch mode.
SSH_BATCH="${GIT_SSH_COMMAND:-ssh} -o BatchMode=yes -o ConnectTimeout=5"

if command -v timeout >/dev/null 2>&1; then
    REMOTE=$(GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="$SSH_BATCH" \
        timeout 8 git -C "$REPO_ROOT" ls-remote origin "refs/heads/$BRANCH" 2>/dev/null | cut -f1)
else
    REMOTE=$(GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="$SSH_BATCH" \
        git -C "$REPO_ROOT" ls-remote origin "refs/heads/$BRANCH" 2>/dev/null | cut -f1)
fi

# Guard the read rather than relying on `2>/dev/null`: redirections are processed
# left to right, so `< "$SEEN"` fails and the SHELL reports it before stderr is
# ever redirected. The caller captures stderr into the session banner, so a first
# run on a fresh clone would otherwise show a bogus "No such file" error.
LAST=""
[[ -f "$SEEN" ]] && LAST=$(tr -d '[:space:]' < "$SEEN" 2>/dev/null || true)

# Offline, DNS failure, auth failure and timeout all land here. Leave the stamp
# untouched: silence is correct, a false regression report is not.
if [[ -z "$REMOTE" ]]; then
    echo "SKIP ls-remote-empty (offline, auth failure, or timeout)"
    exit 0
fi

if [[ -z "$LAST" ]]; then
    echo "BASELINE $REMOTE"
    stamp "$REMOTE"
    exit 0
fi

if [[ "$LAST" == "$REMOTE" ]]; then
    echo "OK unchanged $REMOTE"
    exit 0
fi

# Cannot judge direction: the baseline commit is not in this clone (pruned by gc, or the
# stamp came from another machine). Logged rather than passed over silently, because a
# force-push whose dropped commits are also absent locally looks exactly like this --
# the one case that most resembles a real incident is the one we cannot rule on.
if ! git -C "$REPO_ROOT" cat-file -e "${LAST}^{commit}" 2>/dev/null; then
    note "cannot-compare  baseline $LAST absent from this clone; re-baselined to $REMOTE"
    echo "CANNOT-COMPARE baseline $LAST absent locally; re-baselined to $REMOTE"
    stamp "$REMOTE"
    exit 0
fi

if git -C "$REPO_ROOT" merge-base --is-ancestor "$LAST" "$REMOTE" 2>/dev/null; then
    echo "OK advanced ${LAST:0:7} -> ${REMOTE:0:7}"
    stamp "$REMOTE"
    exit 0
fi

DROPPED=$(git -C "$REPO_ROOT" rev-list --count "$REMOTE..$LAST" 2>/dev/null || echo '?')
note "REGRESSED  $LAST -> $REMOTE  ($DROPPED commit(s) dropped)"
printf '    !! ALERT    origin/%s went BACKWARDS: %s commit(s) dropped (%s -> %s)\n' \
    "$BRANCH" "$DROPPED" "${LAST:0:7}" "${REMOTE:0:7}"
printf '                Recover by MERGE, never `reset --hard`. Evidence: %s\n' \
    "${REGLOG/#$REPO_ROOT\//}"
stamp "$REMOTE"
exit 1

#!/usr/bin/env bash
# push-guard.sh — block direct pushes to main/master/production.
#
# Versioned replacement for the inline PreToolUse hook shipped in
# dwarvesf/claude-guardrails (`full/settings.json`, v0.4.0 / 65a41de). Same
# contract: read the PreToolUse payload on stdin, print `BLOCKED: ...` to stderr
# and exit 2 to block; exit 0 to allow.
#
# WHY THIS EXISTS AS A FILE
# The upstream version is a one-line regex embedded in `~/.claude/settings.json`,
# which this harness cannot read or write — so its bug could not be fixed by a PR
# and had to be applied by hand. As a repo script (the pattern already used by
# grep-guard.sh and edit-surface-guard.sh, both symlinked into ~/.claude/hooks/),
# it is versioned, testable, and CI-covered; future fixes are ordinary PRs.
#
# THE BUG BEING FIXED
# Upstream matches:
#     (^|[&|;(])[[:space:]]*git[[:space:]]+push[[:space:]]+.*\b(main|master|production)([[:space:];|&)]|$)
# `.*` is not anchored to the end of the segment, so it spans command
# separators: `git push` in one command combines with a `main` token from a
# LATER, unrelated command. `git push -u origin feat/x; git rev-parse main` was
# blocked — the push was to a feature branch, and `main` belonged to a different
# command entirely. Same bug class as the grep-guard defect fixed in PR #106,
# which is why that guard was also rewritten to evaluate per segment.
#
# THE FIX is to split on command separators FIRST, then apply the same predicate
# anchored at each segment's start. Two details are load-bearing:
#   * The trailing character class is preserved verbatim from upstream. It is
#     what keeps `restore/main-reland-2026-08-14` allowed — the character after
#     `main` is `-`, which is not a terminator. Replacing it with a bare `\b`
#     would introduce a NEW false positive on every branch named `*main*`.
#   * `(` is in the split set because upstream's leading class included it.
#     Without it, `(git push origin main)` would become a false NEGATIVE.
#
# NOT FIXED (pre-existing upstream weaknesses, present before and after — this
# change neither introduces nor closes them; do not read it as hardening):
#   `git push origin "main"` · `if true; then git push origin main; fi`
#   `x=1 git push origin main`   — all ALLOW under both versions.
#
# KNOWN FALSE POSITIVE, both versions: this matches raw command text and has no
# notion of WHICH command is running, so a `git commit` whose message quotes a
# subshell-wrapped push is blocked as if it were the push. Hit while committing
# this very file. Closing it needs quote/word awareness; that is a real change to
# a security control and is tracked in ROADMAP rather than bolted on here, since
# a sloppy attempt risks a false negative — which is strictly worse.
# Workaround: keep such text out of the command line (e.g. `git commit -F -`).

set -uo pipefail

CMD=$(cat | jq -r '.tool_input.command // empty' 2>/dev/null || true)
[ -n "$CMD" ] || exit 0

if printf '%s\n' "$CMD" | tr ';&|(' '\n\n\n\n' \
    | grep -qEi "^[[:space:]]*git[[:space:]]+push[[:space:]]+.*\b(main|master|production)([[:space:];|&)]|$)"
then
    echo "BLOCKED: Direct push to main/master/production. Use a feature branch and PR." >&2
    exit 2
fi

exit 0

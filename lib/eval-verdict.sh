#!/usr/bin/env bash
# Verdict handling for auto-maintain.sh Part B — extracted so it is testable.
#
# The 2026-08-21 03:00 run printed `evaluation complete` over an agent whose own
# final message opened "Blocked — nothing was written to the stack repo." The fix
# was a required machine-readable verdict line plus a path-scoped delta check.
# That fix shipped verified only by a scratchpad harness, which is the same shape
# of gap as the bug it closed: a control with nothing asserting it still works.
#
# Both halves live here as pure functions of their arguments so tests/ can drive
# every branch without running the nightly job. DO NOT RE-INLINE THESE INTO
# auto-maintain.sh — tests/test_auto_maintain_verdict.py asserts that the script
# still sources this file, precisely so that re-inlining fails CI instead of
# quietly orphaning the coverage.
#
# Sourced by scripts/auto-maintain.sh. Defines functions only; no side effects at
# source time, no writes, no git or network calls.

# extract_eval_verdict <transcript-file>
#
# Echoes the last well-formed verdict line, or nothing.
#
# Anchored at ^ and closed at $ deliberately: the agent is told to put the line
# alone on the last line, and a looser match would let the same words quoted
# inside a sentence ("I would have written VERDICT: changed, but the write was
# denied") satisfy the contract while describing the opposite outcome. `tail -1`
# because a transcript may legitimately discuss the format before emitting it.
extract_eval_verdict() {
    grep -oE '^VERDICT: (changed|no-change-required|blocked\b.*)$' "$1" | tail -1
}

# classify_eval_verdict <eval_rc> <verdict> <touched> <base_sha> <closing_lines>
#
# Echoes one or more `LEVEL<TAB>message` lines. LEVEL is INFO or WARN; the caller
# prefixes the package name and routes to info()/warn().
#
# Branch order is load-bearing and is not a style choice:
#
#   1. A non-zero exit is reported first. A verdict parsed out of a crashed
#      session is not evidence of anything — the transcript is.
#   2. A MISSING verdict is a FAILURE, not a pass. CLAUDE_BIN is a self-updating
#      symlink into ~/.local/share/claude/versions/, so this contract will
#      degrade on some future release. Failing loudly is the safe direction,
#      because the entire bug being fixed here was a missing signal read as
#      success. Do not demote this to info().
#   3. `changed` with an empty delta is a warning: the agent claimed a write that
#      is not in the tree.
#
# `touched` MUST be computed scoped by path (CLAUDE.md/HANDOFF.md). A bare HEAD
# comparison would let scripts/win/checkpoint.sh's `chk: HH:MM:SS` auto-commits
# forge a `changed` verdict from an unrelated commit.
classify_eval_verdict() {
    local eval_rc="$1" verdict="$2" touched="$3" base_sha="$4" closing="${5:-}"

    if [[ "$eval_rc" -ne 0 ]]; then
        printf 'WARN\tclaude -p exited %s (non-fatal) — see transcript above\n' "$eval_rc"
    elif [[ -z "$verdict" ]]; then
        printf 'WARN\tNO VERDICT LINE — treating as failure. Agent'"'"'s closing lines:\n'
        printf 'WARN\t%s\n' "$closing"
    elif [[ "$verdict" == VERDICT:\ blocked* ]]; then
        printf 'WARN\t%s — NOTHING WAS WRITTEN\n' "${verdict#VERDICT: }"
    elif [[ "$verdict" == "VERDICT: changed" && -z "$touched" ]]; then
        printf 'WARN\tclaimed '"'"'changed'"'"' but CLAUDE.md/HANDOFF.md are untouched since %s\n' "$base_sha"
    else
        printf 'INFO\t%s\n' "${verdict#VERDICT: }"
    fi
}

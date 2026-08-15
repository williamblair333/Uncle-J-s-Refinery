"""
Behaviour matrix for hooks/discipline/push-guard.sh.

This is a SECURITY control -- the only thing standing between a stray
`git push origin main` and a direct push. So the BLOCK cases matter more than
the ALLOW cases: a fix for false positives that quietly creates a false negative
is strictly worse than the bug it replaces.

The upstream regex (dwarvesf/claude-guardrails v0.4.0) let `.*` span command
separators, so `git push` in one command combined with a `main` token from a
later, unrelated command. `UPSTREAM_FALSE_POSITIVES` pins exactly the cases that
must flip to ALLOW; everything in `MUST_BLOCK` must be unaffected by that change.
"""
import json
import os
import subprocess

import pytest

HOOK = os.path.join(os.path.dirname(__file__), "..", "hooks", "discipline", "push-guard.sh")


def _blocked(cmd: str) -> bool:
    """Run the guard with a PreToolUse payload; True iff it blocks (exit 2)."""
    payload = json.dumps({"tool_input": {"command": cmd}, "session_id": "test"})
    r = subprocess.run(["bash", HOOK], input=payload, capture_output=True, text=True)
    if r.returncode == 2:
        assert "BLOCKED" in r.stderr, f"block must explain itself: {r.stderr!r}"
        return True
    assert r.returncode == 0, f"unexpected exit {r.returncode}: {r.stderr!r}"
    return False


# ── BLOCK: genuine pushes that would update main/master/production ──────────

MUST_BLOCK = [
    "git push origin main",
    "git push\torigin   main",                  # tab + repeated spaces
    "git push -f origin main",
    "git push --force origin +main",
    "git push origin +main:main",
    "git push origin HEAD:main",                # refspec form
    "git push origin refs/heads/main",
    "git push origin master",
    "git push origin production",
    "GIT PUSH ORIGIN MAIN",                     # case-insensitive
    "(git push origin main)",                   # subshell -- why '(' is a split char
    "git push origin main | tee log",
    "git push origin main&",
    "cd /tmp && git push origin main",          # push is the LAST segment
    "git push origin main; echo done",          # push is the FIRST segment
]


@pytest.mark.parametrize("cmd", MUST_BLOCK)
def test_blocks_direct_push(cmd):
    assert _blocked(cmd) is True, f"expected BLOCK: {cmd}"


# ── ALLOW: the false positives this guard exists to fix ────────────────────

UPSTREAM_FALSE_POSITIVES = [
    "git push -u origin feat/x; git rev-parse main",
    "git push -u origin feat/x && git log main",
    "git push origin feature | grep main",
]


@pytest.mark.parametrize("cmd", UPSTREAM_FALSE_POSITIVES)
def test_separator_does_not_leak_main_into_the_push(cmd):
    """`main` belongs to a LATER, unrelated command -- not to the push."""
    assert _blocked(cmd) is False, f"expected ALLOW: {cmd}"


# ── ALLOW: everything else ─────────────────────────────────────────────────

MUST_ALLOW = [
    "git push -u origin restore/main-reland-2026-08-14",   # 'main' inside a branch name
    "git push -u origin feat/origin-main-regression-detector",
    "git push -u origin docs/session-end-2026-08-15",
    "git push origin main:refs/heads/backup",              # pushes main TO backup, not to main
    "git push origin feature",
    "git rev-parse main",                                  # not a push at all
    "git status; echo main",
    "echo 'git push origin main is blocked'",
]


@pytest.mark.parametrize("cmd", MUST_ALLOW)
def test_allows_non_main_pushes(cmd):
    assert _blocked(cmd) is False, f"expected ALLOW: {cmd}"


def test_branch_named_main_something_is_not_a_push_to_main():
    """
    Regression pin for the trailing character class. Replacing it with a bare
    `\\b` would match `main` inside `restore/main-reland-...` and block every
    branch with 'main' in its name -- a NEW false positive worse than the
    original bug. The char after `main` is `-`, which is not a terminator.
    """
    assert _blocked("git push -u origin restore/main-reland-2026-08-14") is False
    assert _blocked("git push origin main") is True


def test_empty_and_malformed_payloads_allow():
    """A guard that crashes on junk input must fail open, not wedge every Bash call."""
    for payload in ["", "not json", "{}", '{"tool_input":{}}']:
        r = subprocess.run(["bash", HOOK], input=payload, capture_output=True, text=True)
        assert r.returncode == 0, f"must allow on {payload!r}, got {r.returncode}"

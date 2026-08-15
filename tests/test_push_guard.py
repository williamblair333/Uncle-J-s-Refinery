"""
Behaviour matrix for hooks/discipline/push-guard.sh.

This is a SECURITY control -- the only thing between a stray `git push origin
main` and a direct push. BLOCK cases therefore matter more than ALLOW cases: a
fix for false positives that quietly creates a false negative is strictly worse
than the bug it replaces.

The guard tokenises with a real POSIX lexer (python3 `shlex`), splits only on
UNQUOTED separators, and applies the rule only where `git push` is genuinely the
command being invoked. Upstream (dwarvesf/claude-guardrails v0.4.0) matched raw
text, which produced two defects this suite pins closed:

  1. `.*` spanned command separators, so `main` in a LATER command blocked a
     feature-branch push.
  2. Separator-splitting ran before anything knew about quoting, so a
     `git commit` whose MESSAGE mentioned a push was blocked as if it were one.

Both had the same root cause: no idea which command was actually running.
"""
import json
import os
import shutil
import subprocess

import pytest

HOOK = os.path.join(os.path.dirname(__file__), "..", "hooks", "discipline", "push-guard.sh")


def _run(cmd: str, env=None):
    payload = json.dumps({"tool_input": {"command": cmd}, "session_id": "test"})
    return subprocess.run(["bash", HOOK], input=payload, capture_output=True,
                          text=True, env=env)


def _blocked(cmd: str) -> bool:
    r = _run(cmd)
    if r.returncode == 2:
        assert "BLOCKED" in r.stderr, f"a block must explain itself: {r.stderr!r}"
        return True
    assert r.returncode == 0, f"unexpected exit {r.returncode}: {r.stderr!r}"
    return False


# ── BLOCK: genuine pushes to a protected branch ────────────────────────────

MUST_BLOCK = [
    "git push origin main",
    "git push\torigin   main",
    "git push -f origin main",
    "git push --force origin +main",
    "git push origin +main:main",
    "git push origin HEAD:main",
    "git push origin refs/heads/main",
    "git push origin master",
    "git push origin production",
    "GIT PUSH ORIGIN MAIN".lower(),
    "(git push origin main)",
    "git push origin main | tee log",
    "git push origin main&",
    "cd /tmp && git push origin main",
    "git push origin main; echo done",
]


@pytest.mark.parametrize("cmd", MUST_BLOCK)
def test_blocks_direct_push(cmd):
    assert _blocked(cmd) is True, f"expected BLOCK: {cmd}"


# ── BLOCK: bypasses upstream allowed. Closing these TIGHTENS the control. ──

CLOSED_BYPASSES = [
    'git push origin "main"',                  # quoting no longer hides the ref
    "git push origin 'main'",
    "if true; then git push origin main; fi",  # leading shell keyword skipped
    "x=1 git push origin main",                # env-assignment prefix skipped
    "git -C /repo push origin main",           # git global option skipped
    "/usr/bin/git push origin main",           # absolute path to git
]


@pytest.mark.parametrize("cmd", CLOSED_BYPASSES)
def test_closes_upstream_bypasses(cmd):
    assert _blocked(cmd) is True, f"expected BLOCK: {cmd}"


# ── ALLOW: separator false positives (the original bug) ───────────────────

SEPARATOR_FALSE_POSITIVES = [
    "git push -u origin feat/x; git rev-parse main",
    "git push -u origin feat/x && git log main",
    "git push origin feature | grep main",
]


@pytest.mark.parametrize("cmd", SEPARATOR_FALSE_POSITIVES)
def test_main_in_a_later_command_is_not_part_of_the_push(cmd):
    assert _blocked(cmd) is False, f"expected ALLOW: {cmd}"


# ── ALLOW: quoting false positives (the second bug) ───────────────────────

QUOTED_FALSE_POSITIVES = [
    'git commit -m "docs: note that (git push origin main) is blocked"',
    "git commit -m 'see git push origin main'",
    "echo 'git push origin main is blocked'",
    'grep -r "git push origin main" docs/',
]


@pytest.mark.parametrize("cmd", QUOTED_FALSE_POSITIVES)
def test_a_command_that_merely_describes_a_push_is_not_a_push(cmd):
    """A `git commit` is not a `git push`, however its message reads."""
    assert _blocked(cmd) is False, f"expected ALLOW: {cmd}"


# ── ALLOW: everything else ────────────────────────────────────────────────

MUST_ALLOW = [
    "git push -u origin restore/main-reland-2026-08-14",
    "git push -u origin feat/origin-main-regression-detector",
    "git push origin main:refs/heads/backup",   # pushes main TO backup; main unchanged
    "git push origin main2",
    "git push origin feature",
    "git push",                                 # no refspec -- parity with upstream
    "git push origin",
    "git rev-parse main",
    "git status; echo main",
]


@pytest.mark.parametrize("cmd", MUST_ALLOW)
def test_allows_everything_else(cmd):
    assert _blocked(cmd) is False, f"expected ALLOW: {cmd}"


def test_branch_named_main_something_is_not_a_push_to_main():
    """
    Regression pin for the ref rule. A protected name counts only as the token's
    LAST component, so `restore/main-reland-...` is allowed. Matching `main`
    anywhere would block every branch with 'main' in its name -- a new false
    positive worse than the original bug.
    """
    assert _blocked("git push -u origin restore/main-reland-2026-08-14") is False
    assert _blocked("git push origin main") is True


# ── Degraded paths must fail CLOSED, never open ───────────────────────────

def test_unparseable_quotes_fail_closed():
    """
    shlex raises on unbalanced quotes. That must fall back to the regex, not
    allow -- otherwise an unterminated quote is a trivial universal bypass.
    """
    assert _blocked('git push origin "main') is True
    assert _blocked("git push -f origin 'main") is True


def test_without_python3_falls_back_and_still_blocks(tmp_path):
    """
    python3 may be absent (e.g. the Windows Git Bash port). The fallback regex
    must still block real pushes; it re-introduces the quote false positive,
    which is degraded but never a false negative.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("cat", "jq", "grep", "tr", "sed", "bash", "env"):
        src = shutil.which(tool)
        if src:
            os.symlink(src, bindir / tool)
    if not (bindir / "grep").exists() or not (bindir / "jq").exists():
        pytest.skip("could not build a python3-free PATH with grep and jq")

    env = {**os.environ, "PATH": str(bindir)}
    assert shutil.which("python3", path=str(bindir)) is None

    assert _run("git push origin main", env=env).returncode == 2
    assert _run("git push origin HEAD:main", env=env).returncode == 2
    assert _run("git push -u origin feat/x", env=env).returncode == 0
    assert _run("git push -u origin restore/main-reland-2026-08-14", env=env).returncode == 0


def test_empty_and_malformed_payloads_allow():
    """A guard that crashes on junk must not wedge every Bash call."""
    for payload in ["", "not json", "{}", '{"tool_input":{}}']:
        r = subprocess.run(["bash", HOOK], input=payload, capture_output=True, text=True)
        assert r.returncode == 0, f"must allow on {payload!r}, got {r.returncode}"

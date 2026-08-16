"""Behaviour matrix for hooks/pre-mortem-guard/surface-write-guard.sh.

A security control. The BLOCK cases matter more than the ALLOW ones: this guard
was versioned in order to fix a logging defect, and a transcription slip that
narrowed detection would trade a cosmetic bug for a real false negative.

So the bulk of this file asserts that every detection pattern still denies, and
one case asserts the regex block is byte-identical to the live installed copy
when that copy is present.

The logging cases pin the actual defect: a multi-line command must produce
exactly ONE physical log line carrying `session=`. Before the fix, `head -c`
truncated bytes rather than lines, so a heredoc spilled across four lines and
stranded `session=` on the last one — which is why a real block on 2026-08-15
was reported as "fired but logged nothing".

pytest + jq. No API calls.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "hooks" / "pre-mortem-guard" / "surface-write-guard.sh"
LIVE_GUARD = Path.home() / ".claude" / "hooks" / "pre-mortem-guard" / "surface-write-guard.sh"

DENY = "deny"


def run_guard(command: str, tmp_path: Path, session_id: str = "sess-0001",
              env_extra: dict | None = None) -> subprocess.CompletedProcess:
    payload = {"tool_input": {"command": command}, "session_id": session_id}
    env = {**os.environ, "SURFACE_GUARD_LOG": str(tmp_path / "hook-blocks.log")}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def blocked(res: subprocess.CompletedProcess) -> bool:
    if not res.stdout.strip():
        return False
    try:
        out = json.loads(res.stdout)
    except ValueError:
        return False
    return out.get("hookSpecificOutput", {}).get("permissionDecision") == DENY


def read_log(tmp_path: Path) -> list[str]:
    p = tmp_path / "hook-blocks.log"
    if not p.exists():
        return []
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ── BLOCK matrix: one case per detection pattern ─────────────────────────────
# These are the cases whose regression would be a false negative.

BLOCK_CASES = [
    ("redirect-to-sh",        "echo 'x' > /opt/proj/foo/scripts/deploy.sh"),
    ("redirect-quoted",       "echo 'x' > \"my script.sh\""),
    ("redirect-to-hooks-dir", "cat payload > /home/u/.claude/hooks/thing.txt"),
    ("redirect-midcommand",   "echo x > setup.sh && echo done"),
    ("sed-inplace-empty-suffix", 'sed -i "" build.sh'),
    ("python-open-write",     "python3 -c \"open('guard.sh','w').write('x')\""),
    ("python-open-append",    "python3 -c \"open('guard.py','a').write('x')\""),
    ("ruby-surface",          "ruby -e 'File.write(\"setup.sh\", \"x\")'"),
    ("node-surface",          "node -e 'fs.writeFileSync(\"build.sh\",\"x\")'"),
    ("awk-redirect",          "awk '{print}' in.txt > out.sh"),
    ("cp-to-surface",         "cp /tmp/evil.sh /opt/proj/x/scripts/good.sh"),
    ("mv-to-surface",         "mv /tmp/evil /opt/proj/x/hooks/guard.sh"),
]


@pytest.mark.parametrize("name,cmd", BLOCK_CASES, ids=[c[0] for c in BLOCK_CASES])
def test_surface_writes_are_blocked(name, cmd, tmp_path):
    res = run_guard(cmd, tmp_path)
    assert blocked(res), f"{name}: NOT blocked — false negative.\ncmd={cmd}\nstdout={res.stdout}"


# ── KNOWN GAPS — pre-existing false negatives, pinned not fixed ──────────────
# Verified 2026-08-15 to behave IDENTICALLY in the live installed guard, so these
# are not regressions from versioning. They are NOT fixed here on purpose: this
# PR's job is the logging defect, and widening a write-guard's detection is a
# separate change whose risk is false positives blocking legitimate work.
#
# Two root causes:
#   * REDIR_RE's SURF_EXT and SURF_FILE branches both end in [[:space:];|&$"'],
#     a REQUIRED trailing delimiter. At end-of-command there is no trailing
#     character, so the match fails. `> setup.sh` at the end of a line is missed;
#     `> setup.sh && echo done` is caught.
#   * SED_RE and PERL_RE allow only [[:space:]a-zA-Z0-9='"] between the flag and
#     the filename. Neither `/` nor `.` is in that class, so the match dies at
#     the first slash of `s/a/b/` or the dot of `-i.bak`.
#
# SED_RE is the worst of these and deserves calling out: probing every common
# form found that it fires ONLY on `sed -i "" file.sh`, the macOS empty-suffix
# spelling. `sed -i 's/a/b/' f.sh`, `sed -i.bak … f.yml` and `sed -i -e … f.sh`
# — i.e. essentially all GNU sed usage — are allowed through. The one passing
# BLOCK case above is therefore not representative, and is kept only to prove
# the pattern is not entirely dead.
#
# strict=True on purpose: when these are closed, the xfail turns into an
# unexpected pass and CI fails, forcing this list to be updated rather than
# silently rotting. Tracked in ROADMAP.

KNOWN_GAPS = [
    ("append-to-sh-eol",       "echo 'x' >> setup.sh"),
    ("redirect-settings-eol",  "echo '{}' > settings.json"),
    ("redirect-claude-md-eol", "echo hi > CLAUDE.md"),
    ("sed-gnu-slashes",        "sed -i 's/a/b/' install.sh"),
    ("sed-suffix-dot",         "sed -i.bak 'sXaXbX' config.yml"),
    ("sed-dash-e",             "sed -i -e foo build.sh"),
    ("perl-inplace-slashes",   "perl -pi -e 's/a/b/' deploy.sh"),
]


@pytest.mark.parametrize("name,cmd", KNOWN_GAPS, ids=[c[0] for c in KNOWN_GAPS])
@pytest.mark.xfail(strict=True, reason="known pre-existing detection gap; see ROADMAP")
def test_known_detection_gaps(name, cmd, tmp_path):
    res = run_guard(cmd, tmp_path)
    assert blocked(res), f"{name}: not blocked"


# ── ALLOW matrix: the guard must not block ordinary work ─────────────────────

ALLOW_CASES = [
    ("read-only-cat",     "cat /opt/proj/x/scripts/deploy.sh"),
    ("git-status",        "git status --short"),
    ("redirect-to-txt",   "echo hi > /tmp/notes.txt"),
    ("redirect-to-md",    "echo hi > README.md"),
    ("pipe-to-grep",      "cat foo.log | grep error"),
    ("ls",                "ls -la /opt/proj"),
]


@pytest.mark.parametrize("name,cmd", ALLOW_CASES, ids=[c[0] for c in ALLOW_CASES])
def test_ordinary_commands_are_allowed(name, cmd, tmp_path):
    res = run_guard(cmd, tmp_path)
    assert not blocked(res), f"{name}: false positive — blocked an ordinary command.\ncmd={cmd}"
    assert res.returncode == 0


# ── the logging defect this file exists to fix ───────────────────────────────

def test_multiline_command_writes_exactly_one_log_line(tmp_path):
    """The defect: `head -c` cuts bytes, not lines.

    A heredoc previously wrote four physical lines with `session=` stranded on
    the last, so searching for a BLOCKED line carrying the session id found
    nothing and the block was reported as unlogged.
    """
    cmd = (
        "mkdir -p ~/.uncle-j-memory/memory\n"
        "cat >> ~/.uncle-j-memory/memory/audit-baselines.md <<'EOF'\n"
        "\n"
        "## [AUDIT BASELINE] some heading\n"
        "EOF\n"
        "echo done > /opt/proj/x/scripts/after.sh"
    )
    res = run_guard(cmd, tmp_path, session_id="7fff9c86-ca82-4f0e-9049-17c3ab60b2bf")
    assert blocked(res)

    lines = read_log(tmp_path)
    assert len(lines) == 1, f"expected 1 log line, got {len(lines)}: {lines}"
    assert "session=7fff9c86-ca82-4f0e-9049-17c3ab60b2bf" in lines[0]
    assert lines[0].startswith("20"), "log line must start with a timestamp"
    assert "\n" not in lines[0]


def test_log_line_is_greppable_by_session(tmp_path):
    """The weekly review searches for BLOCKED + session= on one line."""
    run_guard("printf 'a\\nb' > /opt/proj/x/scripts/x.sh", tmp_path, session_id="abc-123")
    lines = read_log(tmp_path)
    assert len(lines) == 1
    assert re.search(r"BLOCKED surface-write-guard .*session=abc-123", lines[0])


def test_tabs_and_carriage_returns_collapsed(tmp_path):
    cmd = "echo\t'x'\r\n> /opt/proj/x/scripts/tabbed.sh"
    run_guard(cmd, tmp_path)
    lines = read_log(tmp_path)
    assert len(lines) == 1
    assert "\t" not in lines[0]
    assert "\r" not in lines[0]


def test_allowed_command_writes_no_log_line(tmp_path):
    run_guard("git status", tmp_path)
    assert read_log(tmp_path) == []


# ── fail-loud on missing jq (was: silently allow everything) ─────────────────

def test_missing_jq_fails_loudly_instead_of_allowing(tmp_path):
    """Without jq the old guard parsed an empty CMD and exit 0'd — silently
    allowing every command it exists to screen."""
    fake_bin = tmp_path / "emptybin"
    fake_bin.mkdir()
    for tool in ("bash", "grep", "date", "printf", "tr", "head", "cat", "echo", "sed"):
        real = shutil.which(tool)
        if real:
            (fake_bin / tool).symlink_to(real)

    res = subprocess.run(
        ["bash", str(GUARD)],
        input=json.dumps({"tool_input": {"command": "echo x > evil.sh"}, "session_id": "s"}),
        capture_output=True,
        text=True,
        env={"PATH": str(fake_bin), "HOME": str(tmp_path)},
        timeout=30,
    )
    assert res.returncode != 0, "guard must not exit 0 when jq is unavailable"
    assert "jq not found" in res.stderr


def test_empty_command_is_allowed(tmp_path):
    res = run_guard("", tmp_path)
    assert res.returncode == 0
    assert not blocked(res)


# ── the ported regexes must not have drifted ─────────────────────────────────

REGEX_VARS = ["SURF_EXT", "SURF_PATH", "SURF_FILE", "REDIR_RE", "SED_RE",
              "PY_RE", "PERL_RE", "RUBY_RE", "NODE_RE", "AWK_RE", "CP_RE"]


def _extract_regex_lines(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        for var in REGEX_VARS:
            if line.startswith(f"{var}="):
                out[var] = line
    return out


def test_all_regex_definitions_present():
    defs = _extract_regex_lines(GUARD)
    missing = [v for v in REGEX_VARS if v not in defs]
    assert not missing, f"detection regexes missing from the versioned guard: {missing}"


@pytest.mark.skipif(not LIVE_GUARD.exists(), reason="live guard not installed on this machine")
def test_regexes_byte_identical_to_live_guard():
    """The versioned copy must detect exactly what the live one detects.

    Only the jq check and the log line were allowed to change.
    """
    repo_defs = _extract_regex_lines(GUARD)
    live_defs = _extract_regex_lines(LIVE_GUARD)
    for var in REGEX_VARS:
        assert repo_defs.get(var) == live_defs.get(var), (
            f"{var} differs from the live guard — detection may have narrowed.\n"
            f"repo: {repo_defs.get(var)!r}\nlive: {live_defs.get(var)!r}"
        )

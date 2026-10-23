"""Behaviour matrix for hooks/discipline/edit-surface-guard.sh.

The guard blocks Edit/Write on surface files (.sh/.py/.yaml/…, hooks/, scripts/…)
until a pre-mortem clearance token exists. These tests run with NO token, so a
surface path must be denied and a non-surface path allowed.

2026-10-16: a Write to a scratch file under /tmp is not a surface edit. A /tmp
path is exempt only when it RESOLVES under /tmp (no `..` or symlink escape) and is
not the pre-mortem token path.

UNCLE_J_PROJ_ROOT points the guard's log at a nonexistent dir so these runs don't
add session=test noise to the live state/hook-blocks.log.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "hooks" / "discipline" / "edit-surface-guard.sh"
SESSION = "test-edit-surface-no-token"


def denied(file_path: str, tmp_path: Path) -> bool:
    payload = {"tool_input": {"file_path": file_path}, "session_id": SESSION}
    env = {**os.environ, "UNCLE_J_PROJ_ROOT": str(tmp_path / "noproj")}
    r = subprocess.run(["bash", str(GUARD)], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, timeout=30)
    return '"deny"' in r.stdout.replace(" ", "")


@pytest.fixture(autouse=True)
def _no_token():
    assert not Path(f"/tmp/premortem-cleared-{SESSION}").exists()


DENY = [
    "/opt/proj/x/scripts/deploy.sh",
    "/opt/proj/x/src/app.py",
    "/home/u/.claude/settings.json",
    "/tmp/../opt/proj/x/hooks/a.sh",          # `..` escape
    "/tmp/premortem-cleared-abc.sh",          # token path is never exempt
]

ALLOW = [
    "/opt/proj/x/README.md",                  # not a surface file
    "/tmp/claude-1000/s/scratchpad/probe.py",
    "/tmp/claude-1000/s/scratchpad/rehearsal.yaml",
    "/tmp/run.sh",
]


@pytest.mark.parametrize("path", DENY)
def test_surface_paths_denied_without_token(path, tmp_path):
    assert denied(path, tmp_path), f"expected DENY: {path}"


@pytest.mark.parametrize("path", ALLOW)
def test_non_surface_and_tmp_scratch_allowed(path, tmp_path):
    assert not denied(path, tmp_path), f"expected ALLOW: {path}"


def test_symlink_out_of_tmp_denied(tmp_path):
    assert str(tmp_path.resolve()).startswith("/tmp/")
    link = tmp_path / "l"
    link.symlink_to(REPO_ROOT / "hooks")
    assert denied(f"{link}/a.sh", tmp_path)


# --- 2026-10-23: surface list reviewed against hook-blocks.log + red-team ----------

SURFACE_ADDED = [
    "/opt/proj/x/.mcp.json",                  # PR #105 incident
    "/opt/proj/x/.claude/settings.local.json",
    "/opt/proj/x/justfile",
    "/home/u/.config/systemd/user/scout.service",
    "/home/u/.config/systemd/user/scout.timer",
    "/opt/proj/x/deploy.SH",                  # extensions are case-blind
    "/opt/proj/x/Tool.PY",
    "/opt/proj/x/tests/conftest.py",          # runs at collection: stays gated
    "/opt/proj/x/hooks/tests/test_guard.py",  # guard dirs never exempt their tests
    "/opt/proj/x/scripts/test_helper.py",
]

TEST_MODULES_ALLOWED = [
    "/opt/proj/x/tests/test_parser.py",
    "/opt/proj/x/tests/unit/parser_test.py",
    "/opt/proj/x/test/test_cli.py",
]


@pytest.mark.parametrize("path", SURFACE_ADDED)
def test_added_surfaces_denied_without_token(path, tmp_path):
    assert denied(path, tmp_path), f"expected DENY: {path}"


@pytest.mark.parametrize("path", TEST_MODULES_ALLOWED)
def test_test_modules_are_not_surfaces(path, tmp_path):
    assert not denied(path, tmp_path), f"expected ALLOW: {path}"


def test_non_surface_name_resolving_onto_a_surface_is_denied(tmp_path):
    # Edit/Write follow symlinks: /tmp/notes.txt -> <repo>/hooks/x.sh edits the hook.
    link = tmp_path / "notes.txt"
    link.symlink_to(REPO_ROOT / "hooks" / "discipline" / "grep-guard.sh")
    assert denied(str(link), tmp_path)
    tlink = tmp_path / "tests"
    tlink.mkdir()
    (tlink / "test_x.py").symlink_to(REPO_ROOT / "hooks" / "discipline" / "grep-guard.sh")
    assert denied(str(tlink / "test_x.py"), tmp_path)


def _with_token(tmp_path, content, session):
    tok = Path(f"/tmp/premortem-cleared-{session}")
    tok.write_text(content)
    try:
        payload = {"tool_input": {"file_path": "/opt/proj/x/scripts/a.sh"}, "session_id": session}
        env = {**os.environ, "UNCLE_J_PROJ_ROOT": str(tmp_path / "noproj")}
        r = subprocess.run(["bash", str(GUARD)], input=json.dumps(payload),
                           capture_output=True, text=True, env=env, timeout=30)
        return '"deny"' in r.stdout.replace(" ", "")
    finally:
        tok.unlink(missing_ok=True)


def test_valid_token_allows(tmp_path):
    import time
    s = f"test-esg-valid-{os.getpid()}"
    assert not _with_token(tmp_path, json.dumps({"ts": int(time.time()), "status": "PRE-MORTEM-COMPLETE"}), s)


@pytest.mark.parametrize("ts", ['"now"', '"a[0]"', "99999999999", '"1e3"', "-5", '"$(id)"'])
def test_forged_token_timestamps_denied(tmp_path, ts):
    # ts reached bash arithmetic raw: "now" never expired, a future ts never expired,
    # and an array subscript could run a command.
    s = f"test-esg-ts-{os.getpid()}"
    assert _with_token(tmp_path, '{"ts": %s, "status": "PRE-MORTEM-COMPLETE"}' % ts, s)

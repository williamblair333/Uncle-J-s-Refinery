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

"""features/dcup/install.sh + the refinery-doctor dcup-guard check.

Everything runs against a temp HOME, bin dir and registry dir. No writes to the real
~/.claude, ~/.local/bin or /opt/lib/docker-port-registry.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FEATURE = REPO_ROOT / "features" / "dcup"
INSTALL = FEATURE / "install.sh"
DOCTOR = REPO_ROOT / "scripts" / "refinery-doctor.sh"
MARKER = "dcup:guard"


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    e = {**os.environ, "HOME": str(home), "DCUP_REGISTRY_DIR": str(tmp_path / "registry"),
         "DCUP_BIN_DIR": str(tmp_path / "bin"), "DCUP_ALLOW_WORKTREE": "1"}
    e.pop("DCUP_SETTINGS", None)
    return e


def settings(env) -> dict:
    return json.loads((Path(env["HOME"]) / ".claude" / "settings.json").read_text())


def run(env, *args, script=INSTALL):
    return subprocess.run(["bash", str(script), *args], env=env, capture_output=True,
                          text=True, timeout=60)


def guard_commands(cfg):
    return [h["command"] for e in cfg.get("hooks", {}).get("PreToolUse", [])
            for h in e.get("hooks", []) if MARKER in h.get("command", "")]


def test_install_registers_once_and_keeps_other_hooks(env):
    path = Path(env["HOME"]) / ".claude" / "settings.json"
    other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "bash other.sh"}]}
    path.write_text(json.dumps({"env": {"A": "1"}, "hooks": {"PreToolUse": [other]}}))

    r = run(env)
    assert r.returncode == 0, r.stderr
    cfg = settings(env)
    assert cfg["env"] == {"A": "1"}
    assert other in cfg["hooks"]["PreToolUse"]
    cmds = guard_commands(cfg)
    assert len(cmds) == 1 and str(FEATURE / "dcup_guard.py") in cmds[0]
    assert (path.parent / "settings.json.bak").exists()

    before = path.read_text()
    assert run(env).returncode == 0
    assert path.read_text() == before, "re-run must change nothing"

    link = Path(env["DCUP_BIN_DIR"]) / "dcup"
    assert link.is_symlink() and link.resolve() == (FEATURE / "dcup").resolve()
    reg = Path(env["DCUP_REGISTRY_DIR"])
    assert (reg / "registry.lock").exists() and (reg / "port-exceptions.toml").exists()


def test_check_and_uninstall(env):
    assert run(env, "--check").stdout.strip().splitlines()[-1] == "missing"
    run(env)
    assert run(env, "--check").stdout.strip().splitlines()[-1] == "installed"
    assert run(env, "--uninstall").returncode == 0
    assert guard_commands(settings(env)) == []
    assert not (Path(env["DCUP_BIN_DIR"]) / "dcup").exists()
    assert run(env, "--check").stdout.strip().splitlines()[-1] == "missing"


def test_regular_file_in_bin_is_left_alone(env):
    bindir = Path(env["DCUP_BIN_DIR"])
    bindir.mkdir()
    (bindir / "dcup").write_text("#!/bin/sh\necho mine\n")
    r = run(env)
    assert r.returncode == 0
    assert (bindir / "dcup").read_text() == "#!/bin/sh\necho mine\n"
    assert "regular file" in r.stderr


def test_existing_registry_db_untouched(env):
    reg = Path(env["DCUP_REGISTRY_DIR"])
    reg.mkdir()
    (reg / "ports.db").write_bytes(b"sentinel")
    (reg / "port-exceptions.toml").write_text("a:b:1:x\n")
    run(env)
    assert (reg / "ports.db").read_bytes() == b"sentinel"
    assert (reg / "port-exceptions.toml").read_text() == "a:b:1:x\n"


def test_refuses_to_install_from_a_worktree(env, tmp_path):
    wt = tmp_path / "repo" / ".claude" / "worktrees" / "x" / "features" / "dcup"
    shutil.copytree(FEATURE, wt)
    e = {**env}
    e.pop("DCUP_ALLOW_WORKTREE")
    r = run(e, script=wt / "install.sh")
    assert r.returncode == 1 and "worktree" in r.stderr
    assert not (Path(env["HOME"]) / ".claude" / "settings.json").exists()


def test_registered_command_blocks_and_survives_a_moved_checkout(env, tmp_path):
    moved = tmp_path / "moved"
    shutil.copytree(FEATURE, moved)
    e = {**env, "DCUP_SETTINGS": str(tmp_path / "s.json")}
    assert run(e, script=moved / "install.sh").returncode == 0
    cmd = guard_commands(json.loads((tmp_path / "s.json").read_text()))[0]
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "docker compose up -d"}})
    hook_env = {k: v for k, v in os.environ.items() if k != "DCUP_GUARD"}
    r = subprocess.run(["sh", "-c", cmd], input=payload, capture_output=True, text=True,
                       env=hook_env, timeout=30)
    assert r.returncode == 2 and "dcup" in r.stderr
    shutil.rmtree(moved)
    r = subprocess.run(["sh", "-c", cmd], input=payload, capture_output=True, text=True,
                       env=hook_env, timeout=30)
    assert r.returncode == 0, "a missing guard must be a no-op, never a blocked Bash call"


def test_vendored_dcup_honours_registry_dir(env):
    r = subprocess.run(["bash", str(FEATURE / "dcup"), "list"], env=env, capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0
    assert "No registry" in r.stdout


def test_doctor_reports_then_fixes(env):
    r = subprocess.run(["bash", str(DOCTOR), "--check", "dcup-guard"], env=env,
                       capture_output=True, text=True, timeout=60)
    assert "dcup guard hook" in r.stderr and r.returncode == 1
    r = subprocess.run(["bash", str(DOCTOR), "--fix", "--check", "dcup-guard"], env=env,
                       capture_output=True, text=True, timeout=60)
    assert "FIXED" in r.stderr
    assert len(guard_commands(settings(env))) == 1
    r = subprocess.run(["bash", str(DOCTOR), "--check", "dcup-guard"], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "registered" in r.stderr

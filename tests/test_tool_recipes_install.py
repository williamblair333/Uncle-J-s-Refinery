"""features/tool-recipes: the installer is idempotent and keeps other hooks; the hook never fails."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INSTALL = REPO / "features" / "tool-recipes" / "install.sh"
HOOK = REPO / "features" / "tool-recipes" / "hooks" / "session-start.sh"
OTHER = {"hooks": [{"type": "command", "command": "/x/other.sh"}]}

needs_just = pytest.mark.skipif(shutil.which("just") is None, reason="just not installed")


def run(cmd, home, proj_root, stdin="", cwd=None):
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               PROJ_ROOT=str(proj_root), XDG_STATE_HOME=str(home / ".state"))
    env.pop("GLOBAL_JUSTFILE", None)
    return subprocess.run(cmd, env=env, input=stdin, capture_output=True, text=True, cwd=cwd, timeout=60)


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    (h / ".claude").mkdir(parents=True)
    (h / ".claude" / "settings.json").write_text(json.dumps({"model": "keep", "hooks": {"SessionStart": [OTHER]}}))
    return h


@pytest.fixture
def proj_root(tmp_path):
    root = tmp_path / "proj"
    (root / "alpha").mkdir(parents=True)
    (root / "alpha" / "justfile").write_text("# say hi\nhi:\n    @echo hi\n")
    return root


def settings(home):
    return json.loads((home / ".claude" / "settings.json").read_text())


@needs_just
def test_install_is_idempotent_and_keeps_other_settings(home, proj_root):
    assert run(["bash", str(INSTALL), "--check"], home, proj_root).returncode == 1
    dry = run(["bash", str(INSTALL), "--dry-run"], home, proj_root)
    assert dry.returncode == 0 and settings(home)["hooks"]["SessionStart"] == [OTHER]

    assert run(["bash", str(INSTALL)], home, proj_root).returncode == 0
    first = (home / ".claude" / "settings.json").read_text()
    assert run(["bash", str(INSTALL)], home, proj_root).returncode == 0
    assert (home / ".claude" / "settings.json").read_text() == first

    s = settings(home)
    assert s["model"] == "keep"
    starts = s["hooks"]["SessionStart"]
    assert starts[0] == OTHER and len(starts) == 2
    assert "tool-recipes:session-start" in starts[1]["hooks"][0]["command"]
    assert (home / ".claude" / "settings.json.bak").is_file()
    assert (home / ".config" / "just" / "justfile").is_file()
    assert run(["bash", str(INSTALL), "--check"], home, proj_root).returncode == 0

    assert run(["bash", str(INSTALL), "--uninstall"], home, proj_root).returncode == 0
    assert settings(home)["hooks"]["SessionStart"] == [OTHER]


def test_installer_refuses_broken_settings(home, proj_root):
    (home / ".claude" / "settings.json").write_text("{not json")
    out = run(["bash", str(INSTALL)], home, proj_root)
    assert out.returncode == 1
    assert (home / ".claude" / "settings.json").read_text() == "{not json"


@needs_just
def test_hook_writes_the_global_justfile_and_exits_0(home, proj_root, tmp_path):
    out = run(["bash", str(HOOK)], home, proj_root, stdin=json.dumps({"cwd": str(proj_root / "alpha")}))
    assert out.returncode == 0
    target = home / ".config" / "just" / "justfile"
    for _ in range(100):  # the sync runs in the background
        if target.is_file():
            break
        subprocess.run(["sleep", "0.1"])
    assert "mod alpha" in target.read_text()


def test_hook_exits_0_on_garbage_and_missing_tools(home, proj_root):
    out = run(["bash", str(HOOK)], home, proj_root / "nowhere", stdin="garbage{")
    assert out.returncode == 0

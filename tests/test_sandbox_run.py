"""sandbox-run: what an agent's code can and can't reach."""
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "features" / "antigravity" / "sandbox-run"
pytestmark = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap not installed")


def run(cwd, *cmd):
    return subprocess.run(["bash", str(SCRIPT), *cmd], cwd=cwd, capture_output=True, text=True, timeout=60)


def test_no_network(tmp_path):
    out = run(tmp_path, "cat", "/proc/net/route")
    assert out.returncode == 0 and len(out.stdout.strip().splitlines()) == 1  # the header only


def test_home_is_empty_but_for_uv(tmp_path):
    out = run(tmp_path, "ls", "-A", str(Path.home()))
    assert set(out.stdout.split()) <= {".local", ".cache"}


def test_only_the_current_directory_is_writable(tmp_path):
    assert run(tmp_path, "touch", "made").returncode == 0 and (tmp_path / "made").exists()
    assert run(tmp_path, "touch", str(Path.home() / "x")).returncode == 0  # tmpfs: gone afterwards
    assert not (Path.home() / "x").exists()
    assert run(tmp_path, "touch", "/usr/x").returncode != 0


def test_refuses_home_as_the_writable_directory():
    assert run(Path.home(), "true").returncode == 2


def test_exit_code_passes_through(tmp_path):
    assert run(tmp_path, "sh", "-c", "exit 7").returncode == 7


SHIMS = SCRIPT.parent / "shims"


def shim(cwd, *cmd):
    import os
    env = {**os.environ, "PATH": f"{SHIMS}:{SCRIPT.parent}:{os.environ['PATH']}"}
    return subprocess.run(list(cmd), cwd=cwd, env=env, capture_output=True, text=True, timeout=60)


def test_a_habitual_python3_runs_sandboxed(tmp_path):
    # agy's PATH has the shims first: `python3` is the real one inside sandbox-run
    code = "import socket\ntry:\n socket.create_connection(('1.1.1.1', 53), 2); print('net')\nexcept OSError: print('offline')"
    out = shim(tmp_path, "python3", "-c", code)
    assert out.returncode == 0 and out.stdout.strip() == "offline"


def test_every_shim_name_is_allowed_and_links_to_the_one_shim():
    import json
    allow = json.loads((SCRIPT.parent / "permissions.json").read_text())["allow"]
    names = [p.name for p in SHIMS.iterdir() if p.name != "_shim"]
    assert names and all(f"command({n})" in allow for n in names)
    assert all((SHIMS / n).resolve() == (SHIMS / "_shim").resolve() for n in names)

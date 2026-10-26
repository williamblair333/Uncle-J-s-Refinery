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

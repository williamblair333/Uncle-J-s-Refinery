"""sandbox-run: what an agent's code can and can't reach."""
import os
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
    names = [p.name for p in SHIMS.iterdir() if p.name not in ("_shim", "local-health")]
    assert names and all(f"command({n})" in allow for n in names)
    assert all((SHIMS / n).resolve() == (SHIMS / "_shim").resolve() for n in names)
    assert "command(local-health)" in allow
    assert (SHIMS / "local-health").is_file()
    assert os.access(SHIMS / "local-health", os.X_OK)


def test_sandbox_run_exports_sandbox_run(tmp_path):
    out = run(tmp_path, "sh", "-c", "echo $SANDBOX_RUN")
    assert out.returncode == 0 and out.stdout.strip() == "1"


def test_shim_passthrough_when_marker_present(tmp_path):
    # Inside sandbox-run, the unforgeable /run/sandbox-run-inside marker exists.
    # The shim must pass through directly without re-invoking sandbox-run.
    out = run(tmp_path, "sh", "-c", f"PATH={SHIMS}:$PATH python3 -c 'import os; print(os.environ.get(\"SANDBOX_RUN\"))'")
    assert out.returncode == 0 and out.stdout.strip() == "1"


def test_shim_sandboxes_when_sandbox_run_set_without_marker(tmp_path):
    # When SANDBOX_RUN=1 is faked in env on the host without the marker,
    # the shim must not trust it and must still route through sandbox-run.
    env = {**os.environ, "PATH": f"{SHIMS}:{SCRIPT.parent}:{os.environ['PATH']}", "SANDBOX_RUN": "1"}
    code = "import os; print(os.path.isdir('/run/sandbox-run-inside'))"
    out = subprocess.run(["python3", "-c", code],
                         cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.strip() == "True"


def test_local_health_rejects_unknown_argument_and_urls(tmp_path):
    lh = SHIMS / "local-health"
    # Unknown argument
    assert subprocess.run([str(lh), "unknown"], capture_output=True).returncode == 2
    # Reject URLs
    assert subprocess.run([str(lh), "http://127.0.0.1:8090/health"], capture_output=True).returncode == 2
    assert subprocess.run([str(lh), "https://example.com"], capture_output=True).returncode == 2
    assert subprocess.run([str(lh), "ftp://127.0.0.1"], capture_output=True).returncode == 2
    # Reject extra arguments
    assert subprocess.run([str(lh), "heretic", "chat"], capture_output=True).returncode == 2


def test_local_health_output_format(tmp_path):
    lh = SHIMS / "local-health"
    out = subprocess.run([str(lh), "heretic"], capture_output=True, text=True)
    assert out.returncode == 0
    parts = out.stdout.strip().split()
    assert len(parts) == 3
    assert parts[0] == "heretic"
    assert parts[1] in ("up", "down")
    assert parts[2].isdigit()


def test_local_health_down_service_prints_exact_000(tmp_path):
    lh = SHIMS / "local-health"
    out = subprocess.run([str(lh), "all"], capture_output=True, text=True)
    assert out.returncode == 0
    lines = [line.split() for line in out.stdout.strip().splitlines()]
    down_lines = [parts for parts in lines if parts[1] == "down"]
    # At least one service is down in test environment
    for parts in down_lines:
        assert parts[2] == "000"

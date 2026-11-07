"""The agy shim must never call itself: on 2026-11-07 that hit the terminal's task limit and
aborted every Claude session sharing it. Each test that starts a shim first proves the
protection is present, and runs under a task cap, so a regression fails instead of forking."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ask_agy  # noqa: E402

pytestmark = pytest.mark.skipif(os.name != "posix", reason="the shim and the task cap are POSIX only")

ANTIGRAVITY = Path(__file__).resolve().parent.parent / "features" / "antigravity"
SHIM = ANTIGRAVITY / "shims" / "_shim"
SANDBOX_RUN = ANTIGRAVITY / "sandbox-run"
SELF_CALLERS = ("basename", "dirname", "readlink")
ALSO_SHIMMED = ("cat", "env", "bash")  # env and bash: a PATH-searched shebang would loop before line 1
SYSTEM_PATH = "PATH=/usr/bin:/bin"


def unprotected_calls(path):
    """Lines that run basename, dirname or readlink through the caller's PATH."""
    found = []
    for line in path.read_text().splitlines():
        code = line.split(" #")[0]
        if code.lstrip().startswith("#"):
            continue
        for tool in SELF_CALLERS:
            for hit in re.finditer(rf"(?:^|[\s(]){tool}\s", code):
                if not code[:hit.start() + 1].rstrip().endswith(SYSTEM_PATH):
                    found.append(line.strip())
    return found


def _cap_tasks(limit):
    """A task cap for the child, a little above what this user already runs."""
    import resource
    resource.setrlimit(resource.RLIMIT_NPROC, (limit, resource.getrlimit(resource.RLIMIT_NPROC)[1]))


def run_shimmed(shim_dir, *cmd, **env):
    assert not unprotected_calls(SHIM), "shim calls itself: refusing to start it"
    assert "AGY_SHIM_DEPTH" in SHIM.read_text(), "depth guard missing: refusing to start the shim"
    assert SHIM.read_text().startswith("#!/bin/bash\n"), "PATH-searched shebang: refusing to start the shim"
    current = len(subprocess.run(["ps", "-eLf", "--no-headers"], capture_output=True, text=True).stdout.splitlines())
    limit = current + 256
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=30, cwd=shim_dir.parent,
                          preexec_fn=lambda: _cap_tasks(limit),
                          env={**os.environ, "PATH": f"{shim_dir}:{shim_dir.parent / 'bin'}:/usr/bin:/bin", **env})


@pytest.fixture
def shim_dir(tmp_path):
    """Every helper the shim could reach for is itself the shim; sandbox-run is a stand-in."""
    shims = tmp_path / "sh"
    shims.mkdir()
    for name in (*SELF_CALLERS, *ALSO_SHIMMED):
        (shims / name).symlink_to(SHIM)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "sandbox-run"
    fake.write_text('#!/bin/sh\necho "sandboxed: $*"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return shims


def test_neither_script_calls_a_shimmable_helper_through_the_callers_path():
    assert unprotected_calls(SHIM) == []
    assert unprotected_calls(SANDBOX_RUN) == []


@pytest.mark.parametrize("tool", [*SELF_CALLERS, *ALSO_SHIMMED])
def test_a_shimmed_command_reaches_sandbox_run_even_when_helpers_are_shimmed(shim_dir, tool):
    out = run_shimmed(shim_dir, str(shim_dir / tool), "hello")
    assert (out.returncode, out.stdout.strip()) == (0, f"sandboxed: {tool} hello"), out.stderr


def test_the_depth_guard_stops_a_loop(shim_dir):
    out = run_shimmed(shim_dir, str(shim_dir / "cat"), "x", AGY_SHIM_DEPTH="32")
    assert out.returncode == 126 and "sandboxed" not in out.stdout


def test_a_crafted_depth_value_is_not_executed(shim_dir, tmp_path):
    marker = tmp_path / "ran"
    out = run_shimmed(shim_dir, str(shim_dir / "cat"), "x", AGY_SHIM_DEPTH=f"a[$(touch {marker})]")
    assert out.returncode == 0 and not marker.exists()


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap not installed")
def test_real_sandbox_run_with_its_helpers_shimmed(shim_dir, tmp_path):
    assert not unprotected_calls(SANDBOX_RUN), "sandbox-run calls a shim: refusing to start it"
    (tmp_path / "bin" / "sandbox-run").unlink()
    (tmp_path / "bin" / "sandbox-run").symlink_to(SANDBOX_RUN)
    (tmp_path / "note").write_text("inside\n")
    out = run_shimmed(shim_dir, str(shim_dir / "cat"), "note")
    assert (out.returncode, out.stdout.strip()) == (0, "inside"), out.stderr


def test_a_missing_agy_is_reported_as_missing(tmp_path):
    out = ask_agy.ask("hi", agy_bin=str(tmp_path / "nope"), cwd=str(tmp_path))
    assert out == {"ok": False, "error": f"agy not found: {tmp_path / 'nope'}"}


def test_ask_caps_tasks_for_agy(tmp_path):
    seen = tmp_path / "limit.json"
    agy = tmp_path / "agy"
    agy.write_text(f"#!{sys.executable}\nimport json, resource\n"
                   f"json.dump(resource.getrlimit(resource.RLIMIT_NPROC)[0], open({str(seen)!r}, 'w'))\n")
    agy.chmod(agy.stat().st_mode | stat.S_IXUSR)
    ask_agy.ask("hi", agy_bin=str(agy), cwd=str(tmp_path))
    assert json.loads(seen.read_text()) <= ask_agy.AGY_MAX_USER_TASKS

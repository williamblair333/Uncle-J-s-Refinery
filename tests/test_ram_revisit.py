"""scripts/ram_revisit.sh: remind to revisit the local 125B model once RAM is >= 120 GiB.

Silent below the threshold, a single line at or above it, and always exit 0 — it runs
inside the healthcheck, so an error here must never fail or abort that.
"""

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ram_revisit.sh"


def run(tmp_path: Path, meminfo: str | None, **env_extra) -> subprocess.CompletedProcess:
    path = tmp_path / "meminfo"
    if meminfo is not None:
        path.write_text(meminfo)
    env = {**os.environ, "RAM_REVISIT_MEMINFO": str(path), **env_extra}
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=10)


def kib(gib: float) -> str:
    return f"MemTotal:       {int(gib * 1024 * 1024)} kB\nMemFree:  1 kB\n"


def test_silent_on_current_46_gib_machine(tmp_path):
    r = run(tmp_path, kib(46.8))
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


def test_silent_just_below_threshold(tmp_path):
    r = run(tmp_path, kib(119.9))
    assert r.returncode == 0 and r.stdout == ""


def test_reminds_at_128_gib(tmp_path):
    r = run(tmp_path, kib(125.7))  # what a 128 GB box typically reports
    assert r.returncode == 0
    assert len(r.stdout.strip().splitlines()) == 1
    assert "125B" in r.stdout and "research-later" in r.stdout


def test_threshold_override(tmp_path):
    r = run(tmp_path, kib(46.8), RAM_REVISIT_GIB="40")
    assert r.returncode == 0 and "125B" in r.stdout


def test_missing_meminfo_is_silent_and_exits_zero(tmp_path):
    r = run(tmp_path, None)
    assert r.returncode == 0 and r.stdout == ""


def test_garbage_meminfo_is_silent_and_exits_zero(tmp_path):
    r = run(tmp_path, "not a meminfo file\n")
    assert r.returncode == 0 and r.stdout == ""


def test_garbage_threshold_is_silent_and_exits_zero(tmp_path):
    r = run(tmp_path, kib(128), RAM_REVISIT_GIB="lots")
    assert r.returncode == 0 and r.stdout == ""

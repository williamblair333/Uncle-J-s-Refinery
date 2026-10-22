"""healthcheck.sh's stale_pids_since: which processes started before the package was installed.

The helper is pulled out of healthcheck.sh and run in bash on plain numbers, so the
comparison is tested without real processes, systemd or a venv.
"""
import re
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _helper():
    hc = (_REPO / "healthcheck.sh").read_text(encoding="utf-8")
    return re.search(r"^stale_pids_since\(\) {\n.*?^}\n", hc, re.S | re.M).group(0)


def _stale(since, lines):
    script = f"{_helper()}\nprintf '%s' \"$1\" | stale_pids_since {since}\n"
    out = subprocess.run(["bash", "-c", script, "_", lines], text=True,
                         capture_output=True, check=True).stdout
    return out.split()


def test_only_processes_started_before_the_install_are_stale():
    assert _stale(1000, "11 900\n12 1000\n13 1500\n") == ["11"]


def test_no_processes_or_blank_lines_is_empty():
    assert _stale(1000, "") == []
    assert _stale(1000, "\n\n") == []


def test_a_line_without_a_start_time_is_ignored():
    assert _stale(1000, "11\n12 999\n") == ["12"]

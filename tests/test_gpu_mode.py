"""`just gpu mtw2` costs Klarheit slots for good, so it must refuse without an explicit yes and
never do it silently. The script runs from a copied tree with every outside command stubbed, so
these tests can't touch the real timers, Ollama or state/."""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FLAG = "--accept-klarheit-loss"
COMMANDS = ["systemctl", "docker", "curl", "nvidia-smi", "readlink"]


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "lib").mkdir()
    (tmp_path / "bin").mkdir()
    (tmp_path / "state").mkdir()
    shutil.copy(REPO / "scripts" / "gpu-mode.sh", tmp_path / "scripts" / "gpu-mode.sh")
    calls = tmp_path / "calls.log"
    for name in COMMANDS:
        _script(tmp_path / "bin" / name, f'echo "{name} $*" >> "{calls}"\n')
    _script(tmp_path / "scripts" / "heretic.sh", f'echo "heretic $*" >> "{calls}"\n')
    (tmp_path / "lib" / "notify.sh").write_text(f'notify_send_text() {{ echo "ALERT $1" >> "{calls}"; }}\n')
    (tmp_path / ".env").write_text("TELEGRAM_BOT_TOKEN=1:x\nTELEGRAM_CHAT_ID=2\n")
    return tmp_path


def _script(path, body):
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run(tree, *args):
    env = {**os.environ, "PATH": f"{tree / 'bin'}:{os.environ['PATH']}"}
    return subprocess.run(
        ["bash", str(tree / "scripts" / "gpu-mode.sh"), *args], env=env, capture_output=True, text=True, timeout=30
    )


def _calls(tree):
    log = tree / "calls.log"
    return log.read_text() if log.exists() else ""


def test_mtw2_without_flag_refuses_and_touches_nothing(tree):
    result = _run(tree, "mtw2")
    assert result.returncode == 3
    assert FLAG in result.stderr
    assert _calls(tree) == ""
    assert not (tree / "state" / "gpu-mode").exists()


def test_mtw2_with_flag_stops_timers_and_alerts(tree):
    result = _run(tree, "mtw2", FLAG)
    assert result.returncode == 0, result.stderr
    calls = _calls(tree)
    assert "systemctl --user disable --now" in calls
    assert "docker stop ollama" in calls
    assert "ALERT GPU mode mtw2" in calls
    assert (tree / "state" / "gpu-mode").read_text().strip() == "mtw2"


def test_mtw2_again_needs_no_flag_and_sends_no_second_alert(tree):
    (tree / "state" / "gpu-mode").write_text("mtw2\n")
    result = _run(tree, "mtw2")
    assert result.returncode == 0, result.stderr
    assert "ALERT" not in _calls(tree)


def test_failed_alert_does_not_stop_the_switch(tree):
    (tree / "lib" / "notify.sh").write_text("notify_send_text() { return 1; }\n")
    result = _run(tree, "mtw2", FLAG)
    assert result.returncode == 0, result.stderr
    assert "Telegram alert not sent" in result.stderr
    assert (tree / "state" / "gpu-mode").read_text().strip() == "mtw2"


def test_missing_telegram_credentials_warn_instead_of_silently_skipping(tree):
    (tree / ".env").write_text("")
    env = {k: v for k, v in os.environ.items() if not k.startswith("TELEGRAM_")}
    env["PATH"] = f"{tree / 'bin'}:{env['PATH']}"
    result = subprocess.run(
        ["bash", str(tree / "scripts" / "gpu-mode.sh"), "mtw2", FLAG], env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert "Telegram alert not sent" in result.stderr
    assert "ALERT" not in _calls(tree)


def test_shared_after_mtw2_reports_time_off(tree):
    (tree / "state" / "gpu-mode").write_text("mtw2\n")
    result = _run(tree, "shared")
    assert result.returncode == 0, result.stderr
    calls = _calls(tree)
    assert "ALERT GPU mode shared" in calls and "min off" in calls
    assert "docker start ollama" in calls
    assert not (tree / "state" / "gpu-mode").exists()


def test_failed_heretic_still_brings_klarheit_back_and_exits_nonzero(tree):
    (tree / "state" / "gpu-mode").write_text("mtw2\n")
    _script(tree / "scripts" / "heretic.sh", "exit 1\n")
    result = _run(tree, "shared")
    assert result.returncode == 1
    calls = _calls(tree)
    assert "docker start ollama" in calls
    assert "systemctl --user enable --now" in calls
    assert "Heretic didn't come up" in result.stderr


def test_failure_after_timers_stop_still_records_mtw2(tree):
    _script(tree / "bin" / "docker", "exit 1\n")
    result = _run(tree, "mtw2", FLAG)
    assert result.returncode != 0
    assert (tree / "state" / "gpu-mode").read_text().strip() == "mtw2"


def test_timer_with_no_unit_file_does_not_abort_the_switch(tree):
    _script(tree / "bin" / "readlink", "exit 1\n")
    result = _run(tree, "mtw2", FLAG)
    assert result.returncode == 0, result.stderr
    assert "systemctl --user disable --now" in _calls(tree)


def test_shared_when_already_shared_sends_no_alert(tree):
    result = _run(tree, "shared")
    assert result.returncode == 0, result.stderr
    assert "ALERT" not in _calls(tree)

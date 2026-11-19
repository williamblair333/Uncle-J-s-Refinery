"""notify_send_text must report a failed Telegram send (it used to end in `|| true`)."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(tmp_path, curl_exit, token="123:abc_DEF-9"):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    curl = fakebin / "curl"
    curl.write_text(f"#!/bin/sh\ncat >/dev/null\nexit {curl_exit}\n")
    curl.chmod(0o755)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    env = {
        **os.environ,
        "PATH": f"{fakebin}:{os.environ['PATH']}",
        "TELEGRAM_BOT_TOKEN": token,
        "TELEGRAM_CHAT_ID": "42",
        "TMPDIR": str(tmpdir),
    }
    script = f'source "{ROOT}/lib/notify.sh"; notify_send_text "hello <b>x</b>"'
    r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    return r.returncode


def _leftovers():
    return sorted(Path("/tmp").glob("tg_textpayload_*.json"))


def test_success_returns_zero(tmp_path):
    before = _leftovers()
    assert _run(tmp_path, 0) == 0
    assert _leftovers() == before


def test_http_failure_returns_nonzero(tmp_path):
    before = _leftovers()
    assert _run(tmp_path, 22) == 22
    assert _leftovers() == before, "payload temp file left behind on failure"


def test_malformed_token_returns_nonzero(tmp_path):
    assert _run(tmp_path, 0, token="not a token") != 0


def test_failure_does_not_fail_session_notify_stop_hook(tmp_path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    (fakebin / "curl").write_text("#!/bin/sh\ncat >/dev/null\nexit 7\n")
    (fakebin / "curl").chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fakebin}:{os.environ['PATH']}",
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "TELEGRAM_CHAT_ID": "42",
        "CLAUDE_NOTIFY_ON_STOP": "1",
    }
    r = subprocess.run(
        ["bash", str(ROOT / "scripts/session-notify.sh")],
        input='{"session_id":"abcdef123"}', env=env, capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "Telegram send failed" in r.stderr

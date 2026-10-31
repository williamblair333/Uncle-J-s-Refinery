import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent

_spec = importlib.util.spec_from_file_location("self_check", REPO / "scripts" / "self_check.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)


@pytest.fixture(autouse=True)
def _temp_log(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "LOG", tmp_path / "self-check.jsonl")
    monkeypatch.delenv("SELF_CHECK", raising=False)
    monkeypatch.delenv("SELF_CHECK_MIN_CHARS", raising=False)
    monkeypatch.delenv("SELF_CHECK_LOG", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")


def prompt(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def say(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def transcript(tmp_path, entries):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return {"transcript_path": str(p), "stop_hook_active": False, "cwd": "/x"}


def test_long_reply_blocks(tmp_path):
    hook = transcript(tmp_path, [prompt("go"), say("This is a factual claim to check. " * 70)])
    out = sc.decide(hook)
    assert out is not None
    assert out["decision"] == "block"
    assert out["reason"] == sc.REASON


def test_short_reply_does_not_block(tmp_path):
    hook = transcript(tmp_path, [prompt("go"), say("Short answer under threshold.")])
    assert sc.decide(hook) is None


def test_long_reply_mostly_fenced_code_does_not_block(tmp_path):
    code_block = "```python\n" + ("print('code line')\n" * 200) + "```\n"
    text = f"Explanation before code:\n{code_block}\nSummary after code."
    hook = transcript(tmp_path, [prompt("go"), say(text)])
    assert sc.decide(hook) is None


def test_stop_hook_active_does_not_block(tmp_path):
    hook = transcript(tmp_path, [prompt("go"), say("This is a factual claim to check. " * 70)])
    hook["stop_hook_active"] = True
    assert sc.decide(hook) is None


def test_self_check_off_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_CHECK", "off")
    hook = transcript(tmp_path, [prompt("go"), say("This is a factual claim to check. " * 70)])
    assert sc.decide(hook) is None


def test_sdk_entrypoint_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    hook = transcript(tmp_path, [prompt("go"), say("This is a factual claim to check. " * 70)])
    assert sc.decide(hook) is None


def test_self_check_min_chars_lowers_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_CHECK_MIN_CHARS", "100")
    hook = transcript(tmp_path, [prompt("go"), say("This is a substantive reply exceeding 100 characters threshold easily. " * 3)])
    out = sc.decide(hook)
    assert out is not None
    assert out["decision"] == "block"


def test_empty_transcript_path_falls_back_to_last_assistant_message():
    long_msg = "This is a factual claim to check. " * 70
    hook = {"transcript_path": "", "last_assistant_message": long_msg, "stop_hook_active": False, "cwd": "/x"}
    out = sc.decide(hook)
    assert out is not None
    assert out["decision"] == "block"


def test_hook_script_subprocess_emits_block_and_fails_open(tmp_path):
    sh = REPO / "hooks" / "discipline" / "self-check.sh"
    log_file = tmp_path / "subp_log.jsonl"
    hook = transcript(tmp_path, [prompt("go"), say("This is a factual claim to check. " * 70)])
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        "SELF_CHECK_LOG": str(log_file),
    }
    r = subprocess.run(["bash", str(sh)], input=json.dumps(hook), capture_output=True, text=True, env=env)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["decision"] == "block"
    assert data["reason"] == sc.REASON

    r_inv = subprocess.run(["bash", str(sh)], input="invalid json", capture_output=True, text=True, env=env)
    assert r_inv.returncode == 0
    assert r_inv.stdout == ""


def test_block_writes_log_without_reply_text(tmp_path, monkeypatch, capsys):
    secret_marker = "sensitive_factual_secret_marker_12345"
    reply = f"Long substantive reply with {secret_marker} " + ("additional prose content " * 80)
    hook = transcript(tmp_path, [prompt("go"), say(reply)])
    log_file = tmp_path / "logged.jsonl"
    monkeypatch.setattr(sc, "LOG", log_file)
    monkeypatch.setenv("SELF_CHECK_LOG", str(log_file))
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(hook)))

    assert sc.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "block"

    assert log_file.exists()
    content = log_file.read_text()
    lines = content.splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["cwd"] == "/x"
    assert rec["chars"] == len(reply)
    assert "ts" in rec
    assert secret_marker not in content

"""skill-suggest.sh Stop hook: the churn guards from 2026-11-01.

The hook fired on every Stop (re-stops forced by self-check included), and each fire ran
a full `claude -p` that loaded every MCP server; 583 of 682 Refinery transcripts were its
children and RAM + swap filled. A fake `claude` records each call so the tests can count
launches and read the argv.
"""
import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "scripts" / "skill-suggest.sh"


def _setup(tmp_path):
    calls = tmp_path / "calls.jsonl"
    fake = tmp_path / "fake-claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"open({str(calls)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:], "
        "'child': os.environ.get('SKILL_SUGGEST_CHILD'), 'stdin': sys.stdin.read()}) + '\\n')\n"
        "print('SKILL_DRAFT: NO')\n")
    fake.chmod(0o755)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "did a thing"}]}}) + "\n")
    env = {k: v for k, v in os.environ.items()
           if k not in ("SKILL_SUGGEST_CHILD", "SKILL_SUGGEST", "CLAUDE_CODE_ENTRYPOINT")}
    env.update(TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="1", SKILL_SUGGEST_CLAUDE=str(fake),
               SKILL_SUGGEST_STATE=str(tmp_path / "state"))
    return calls, transcript, env


def _run(transcript, env, session="sess-aaaa1111", active=False, **extra):
    payload = {"session_id": session, "transcript_path": str(transcript)}
    if active:
        payload["stop_hook_active"] = True
    r = subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), text=True,
                       env={**env, **extra}, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr


def _calls(calls):
    return [json.loads(l) for l in calls.read_text().splitlines()] if calls.exists() else []


def test_child_call_is_stripped(tmp_path):
    calls, t, env = _setup(tmp_path)
    _run(t, env)
    (c,) = _calls(calls)
    argv = c["argv"]
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--tools") + 1] == ""
    assert '{"disableAllHooks":true}' in argv
    assert "--no-session-persistence" in argv
    assert "--dangerously-skip-permissions" not in argv
    assert c["child"] == "1"
    assert "did a thing" in c["stdin"]


def test_restop_does_not_launch(tmp_path):
    calls, t, env = _setup(tmp_path)
    _run(t, env, active=True)
    assert _calls(calls) == []


def test_cooldown_one_run_per_session(tmp_path):
    calls, t, env = _setup(tmp_path)
    for _ in range(3):
        _run(t, env)
    assert len(_calls(calls)) == 1
    _run(t, env, session="sess-bbbb2222")
    assert len(_calls(calls)) == 2


def test_headless_and_child_and_killswitch_skip(tmp_path):
    calls, t, env = _setup(tmp_path)
    _run(t, env, SKILL_SUGGEST_CHILD="1")
    _run(t, env, CLAUDE_CODE_ENTRYPOINT="sdk-cli")
    _run(t, env, SKILL_SUGGEST="off")
    assert _calls(calls) == []

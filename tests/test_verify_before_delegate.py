"""hooks/discipline/verify-before-delegate.sh: first delegation waits for verifiable-task, once."""
import json
import os
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "discipline" / "verify-before-delegate.sh"
SKILL_CALL = {"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "Skill", "input": {"skill": "verifiable-task"}}]}}


def run(tmp_path, payload, transcript_lines=()):
    tr = tmp_path / "t.jsonl"
    tr.write_text("".join(json.dumps(x) + "\n" for x in transcript_lines))
    payload = {"session_id": "sess-1234567890", "transcript_path": str(tr), **payload}
    env = {**os.environ, "HOME": str(tmp_path), "VERIFY_GATE_DIR": str(tmp_path / "vg")}
    return subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, env=env, timeout=10)


def denied(proc):
    return proc.stdout.strip() and json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("tool", ["mcp__delegate__ask_agy", "mcp__delegate__ask_heretic",
                                  "mcp__delegate__ask_openai", "mcp__ask_local__summarize_local", "Agent"])
def test_first_delegation_without_skill_denied_once(tmp_path, tool):
    p = {"tool_name": tool, "tool_input": {"subagent_type": "general-purpose"}}
    first = run(tmp_path, p)
    assert first.returncode == 0 and denied(first)
    assert "verifiable-task" in first.stdout
    second = run(tmp_path, p)
    assert second.returncode == 0 and second.stdout == ""


def test_skill_already_called_allows(tmp_path):
    assert run(tmp_path, {"tool_name": "mcp__delegate__ask_agy"}, [SKILL_CALL]).stdout == ""


@pytest.mark.parametrize("payload", [
    {"tool_name": "Agent", "tool_input": {"subagent_type": "Explore"}},
    {"tool_name": "Agent", "tool_input": {"subagent_type": "claude-code-guide"}},
    {"tool_name": "mcp__delegate__ask_agy", "agent_id": "a123"},
    {"tool_name": "mcp__delegate__make_image"},
    {"tool_name": "mcp__ask_local__local_status"},
    {"tool_name": "Bash", "tool_input": {"command": "ls"}},
])
def test_exempt_calls_pass(tmp_path, payload):
    assert run(tmp_path, payload).stdout == ""


def test_fails_open(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    for raw in ("not json", "", json.dumps({"tool_name": "mcp__delegate__ask_agy", "session_id": "s",
                                            "transcript_path": "/nonexistent/t.jsonl"})):
        r = subprocess.run(["bash", str(HOOK)], input=raw, text=True, capture_output=True, env=env, timeout=10)
        assert r.returncode == 0 and r.stdout == ""

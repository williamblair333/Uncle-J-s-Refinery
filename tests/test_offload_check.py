"""Tests for hooks/discipline/offload-check.sh."""
import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "discipline" / "offload-check.sh"


def run_hook(tmp_path, stdin_data: str | dict):
    env = {**os.environ, "HOME": str(tmp_path)}
    raw = stdin_data if isinstance(stdin_data, str) else json.dumps(stdin_data)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=raw,
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )


def read_logs(tmp_path):
    log_file = tmp_path / ".claude" / "state" / "offload-check.jsonl"
    if not log_file.exists():
        return []
    return [json.loads(line) for line in log_file.read_text().splitlines() if line.strip()]


def test_deny_without_marker(tmp_path):
    payload = {"tool_input": {"prompt": "do some research", "subagent_type": "researcher"}}
    proc = run_hook(tmp_path, payload)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Offload check" in data["hookSpecificOutput"]["permissionDecisionReason"]

    logs = read_logs(tmp_path)
    assert len(logs) == 1
    assert logs[0]["decision"] == "deny"
    assert logs[0]["subagent_type"] == "researcher"


def test_deny_without_subagent_type(tmp_path):
    payload = {"tool_input": {"prompt": "write some code"}}
    proc = run_hook(tmp_path, payload)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["hookSpecificOutput"]["permissionDecision"] == "deny"

    logs = read_logs(tmp_path)
    assert len(logs) == 1
    assert logs[0]["decision"] == "deny"
    assert logs[0]["subagent_type"] == ""


def test_allow_with_claude_only_marker(tmp_path):
    payload = {"tool_input": {"prompt": "CLAUDE-ONLY: needs Artifact tool\nplease create artifact"}}
    proc = run_hook(tmp_path, payload)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""

    logs = read_logs(tmp_path)
    assert len(logs) == 1
    assert logs[0]["decision"] == "allow"


def test_allow_subagent_types(tmp_path):
    for st in ("fork", "claude-code-guide", "statusline-setup"):
        payload = {"tool_input": {"subagent_type": st, "prompt": "help me"}}
        proc = run_hook(tmp_path, payload)
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    logs = read_logs(tmp_path)
    assert len(logs) == 3
    assert [log["subagent_type"] for log in logs] == ["fork", "claude-code-guide", "statusline-setup"]
    assert all(log["decision"] == "allow" for log in logs)


def test_allow_garbage_stdin(tmp_path):
    proc = run_hook(tmp_path, "not json at all {{{")
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""

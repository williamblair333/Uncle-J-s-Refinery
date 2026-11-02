"""features/prompt-triggers/skill_gate.py: skills the router named run before other work."""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "features" / "prompt-triggers" / "skill_gate.py"


def pending(state, skills, session="s1"):
    (state / f"{session}.json").write_text(json.dumps({"skills": skills}))


def call(state, tool, tool_input=None, session="s1", extra=None, env=None):
    event = {"tool_name": tool, "tool_input": tool_input or {}, "session_id": session,
             **(extra or {})}
    return subprocess.run([sys.executable, str(GATE)], input=json.dumps(event),
                          capture_output=True, text=True, timeout=10,
                          env={**os.environ, "SKILL_ROUTER_STATE": str(state), **(env or {})})


def denied(r):
    return r.stdout and json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_no_pending_allows(tmp_path):
    assert call(tmp_path, "Bash").stdout == ""


def test_skill_call_clears_its_name_then_first_other_tool_is_denied_once(tmp_path):
    pending(tmp_path, ["think-wider", "red-team"])
    assert call(tmp_path, "Skill", {"skill": "think-wider"}).stdout == ""
    r = call(tmp_path, "Bash")
    assert denied(r)
    reason = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "red-team" in reason and "think-wider" not in reason
    assert call(tmp_path, "Bash").stdout == ""          # retry goes through


def test_all_named_skills_run_means_no_deny(tmp_path):
    pending(tmp_path, ["superpowers:brainstorming", "referee"])
    call(tmp_path, "Skill", {"skill": "superpowers:brainstorming", "args": "x"})
    call(tmp_path, "Skill", {"skill": "referee"})
    assert call(tmp_path, "Edit").stdout == ""


def test_subagents_and_off_switch_pass(tmp_path):
    pending(tmp_path, ["red-team"])
    assert call(tmp_path, "Bash", extra={"agent_id": "a1"}).stdout == ""
    assert call(tmp_path, "Bash", env={"SKILL_GATE_OFF": "1"}).stdout == ""
    assert denied(call(tmp_path, "Bash"))               # still pending for the main agent


def test_fails_open(tmp_path):
    r = subprocess.run([sys.executable, str(GATE)], input="not json", capture_output=True,
                       text=True, timeout=10, env={**os.environ, "SKILL_ROUTER_STATE": str(tmp_path)})
    assert r.returncode == 0 and r.stdout == ""
    (tmp_path / "s1.json").write_text("{broken")
    assert call(tmp_path, "Bash").stdout == ""
    pending(tmp_path, ["red-team"])
    for odd in ("a string", ["a", "list"]):                 # referee 2026-11-02: non-dict input
        r = subprocess.run([sys.executable, str(GATE)], capture_output=True, text=True, timeout=10,
                           input=json.dumps({"tool_name": "Skill", "tool_input": odd,
                                             "session_id": "s1"}),
                           env={**os.environ, "SKILL_ROUTER_STATE": str(tmp_path)})
        assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


def test_unwritable_state_allows_rather_than_denying_forever(tmp_path):
    pending(tmp_path, ["red-team"])
    os.chmod(tmp_path, 0o500)
    try:
        assert call(tmp_path, "Bash").stdout == ""
    finally:
        os.chmod(tmp_path, 0o700)

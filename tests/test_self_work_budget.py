"""Tests for hooks/discipline/self-work-budget.sh."""
import json
import os
import subprocess
import time
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = Path(os.environ.get("SELF_WORK_HOOK") or REPO_ROOT / "hooks" / "discipline" / "self-work-budget.sh")


def run_hook(tmp_path, stdin_data: str | dict, env_extra: dict | None = None):
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "SELF_WORK_DIR": str(tmp_path / ".claude" / "state" / "self-work"),
        "SELF_WORK_LOG": str(tmp_path / ".claude" / "state" / "self-work.jsonl"),
        **(env_extra or {}),
    }
    raw = stdin_data if isinstance(stdin_data, str) else json.dumps(stdin_data)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=raw,
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )


def read_logs(tmp_path, log_path: Path | None = None):
    target = log_path or (tmp_path / ".claude" / "state" / "self-work.jsonl")
    if not target.exists():
        return []
    return [json.loads(line) for line in target.read_text().splitlines() if line.strip()]


def test_budget_exceeded_denies_once_then_allows(tmp_path):
    env = {"SELF_WORK_BUDGET": "2"}
    session_id = "test-session-12345678"
    cwd = "/opt/proj/my-project"

    # Call 1: Read -> allow
    payload1 = {"tool_name": "Read", "session_id": session_id, "cwd": cwd}
    proc1 = run_hook(tmp_path, payload1, env)
    assert proc1.returncode == 0
    assert proc1.stdout.strip() == ""

    # Call 2: Write -> allow
    payload2 = {"tool_name": "Write", "session_id": session_id, "cwd": cwd}
    proc2 = run_hook(tmp_path, payload2, env)
    assert proc2.returncode == 0
    assert proc2.stdout.strip() == ""

    # Call 3: Read -> count 3 exceeds budget 2 -> deny once
    payload3 = {"tool_name": "Read", "session_id": session_id, "cwd": cwd}
    proc3 = run_hook(tmp_path, payload3, env)
    assert proc3.returncode == 0
    data = json.loads(proc3.stdout)
    assert data["hookSpecificOutput"]["permissionDecision"] == "deny"
    reason = data["hookSpecificOutput"]["permissionDecisionReason"]
    assert "Self-work budget: 3 tool calls without delegating" in reason
    assert "Hand the next bounded piece to ask_agy" in reason
    assert "Retry to continue if this genuinely needs Claude." in reason

    # Call 4: Retry of Read -> count reset to 0 so next call is 1 <= 2 -> allow
    proc4 = run_hook(tmp_path, payload3, env)
    assert proc4.returncode == 0
    assert proc4.stdout.strip() == ""

    logs = read_logs(tmp_path)
    assert len(logs) == 4
    assert [log["decision"] for log in logs] == ["allow", "allow", "deny", "allow"]
    assert [log["tool"] for log in logs] == ["Read", "Write", "Read", "Read"]


@pytest.mark.parametrize("edit_tool", ["Edit", "Write", "MultiEdit", "NotebookEdit"])
def test_edits_over_budget_never_denied_deny_carries_over(tmp_path, edit_tool):
    """A parallel batch of edits must apply whole: denying one leaves a file half-edited."""
    env = {"SELF_WORK_BUDGET": "2"}
    session_id = "edit-batch-session"
    cwd = "/opt/proj/my-project"
    count_file = tmp_path / ".claude" / "state" / "self-work" / f"{session_id}.count"

    # Four edits in a row: counts 1..4, all allowed even past the budget
    for _ in range(4):
        proc = run_hook(tmp_path, {"tool_name": edit_tool, "session_id": session_id, "cwd": cwd}, env)
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""
    assert count_file.read_text().strip() == "4"

    # The next non-edit self-work call takes the deny and resets the counter
    proc = run_hook(tmp_path, {"tool_name": "Bash", "session_id": session_id, "cwd": cwd,
                               "tool_input": {"command": "ls"}}, env)
    data = json.loads(proc.stdout)
    assert data["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Self-work budget: 5 tool calls" in data["hookSpecificOutput"]["permissionDecisionReason"]
    assert count_file.read_text().strip() == "0"

    logs = read_logs(tmp_path)
    assert [log["decision"] for log in logs] == ["allow"] * 4 + ["deny"]


@pytest.mark.parametrize("delegate_tool", [
    "mcp__delegate__ask_agy",
    "mcp__delegate__ask_heretic",
    "mcp__delegate__ask_openai",
    "mcp__ask_local__ask_local",
    "mcp__ask_local__summarize_local",
    "mcp__ask_local__extract_local",
])
def test_delegation_resets_counter(tmp_path, delegate_tool):
    env = {"SELF_WORK_BUDGET": "2"}
    session_id = "delegation-session-abc"
    cwd = "/opt/proj/test-repo"

    # 2 tool calls: count reaches 2
    for tool in ("Read", "Bash"):
        proc = run_hook(tmp_path, {"tool_name": tool, "session_id": session_id, "cwd": cwd,
                                   "tool_input": {"command": "ls"}}, env)
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    count_file = tmp_path / ".claude" / "state" / "self-work" / f"{session_id}.count"
    assert count_file.read_text().strip() == "2"

    # Delegation tool call resets counter to 0 and logs 'delegate'
    proc_del = run_hook(tmp_path, {"tool_name": delegate_tool, "session_id": session_id, "cwd": cwd}, env)
    assert proc_del.returncode == 0
    assert proc_del.stdout.strip() == ""
    assert count_file.read_text().strip() == "0"

    logs = read_logs(tmp_path)
    assert len(logs) == 3
    assert logs[2]["decision"] == "delegate"
    assert logs[2]["tool"] == delegate_tool

    # Next 2 self-work calls should be allowed without hitting budget
    for tool in ("Grep", "Glob"):
        proc = run_hook(tmp_path, {"tool_name": tool, "session_id": session_id, "cwd": cwd}, env)
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    assert count_file.read_text().strip() == "2"


def test_claude_only_bash_bypass(tmp_path):
    env = {"SELF_WORK_BUDGET": "1"}
    session_id = "claude-only-sess"
    cwd = "/opt/proj/my-project"

    # Bash with CLAUDE-ONLY: line is allowed without counting
    for cmd in (
        "git status\nCLAUDE-ONLY: inspecting git branch",
        "CLAUDE-ONLY: run test suite",
        "echo hi; # CLAUDE-ONLY: necessary host tool",
    ):
        payload = {
            "tool_name": "Bash",
            "session_id": session_id,
            "cwd": cwd,
            "tool_input": {"command": cmd},
        }
        proc = run_hook(tmp_path, payload, env)
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    # Counter should not exist or be 0
    count_file = tmp_path / ".claude" / "state" / "self-work" / f"{session_id}.count"
    if count_file.exists():
        assert count_file.read_text().strip() in ("0", "")

    logs = read_logs(tmp_path)
    assert len(logs) == 3
    assert all(log["decision"] == "allow" for log in logs)


@pytest.mark.parametrize("tool", [
    "Agent",
    "WebSearch",
    "WebFetch",
    "mcp__jcodemunch__search_symbols",
    "mcp__delegate__make_image",
])
def test_unrelated_tools_untouched(tmp_path, tool):
    env = {"SELF_WORK_BUDGET": "1"}
    session_id = "unrelated-sess"
    cwd = "/opt/proj/test-app"

    # Call unrelated tool
    proc = run_hook(tmp_path, {"tool_name": tool, "session_id": session_id, "cwd": cwd}, env)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""

    count_file = tmp_path / ".claude" / "state" / "self-work" / f"{session_id}.count"
    assert not count_file.exists()

    logs = read_logs(tmp_path)
    assert len(logs) == 1
    assert logs[0]["decision"] == "allow"
    assert logs[0]["tool"] == tool


def test_log_lines_carry_project_and_truncated_session(tmp_path):
    session_id = "055eceb3-242b-4ca7-a344-ddfc89bcc1dd"
    cwd = "/opt/proj/Uncle-J-s-Refinery"

    run_hook(tmp_path, {"tool_name": "Read", "session_id": session_id, "cwd": cwd})
    run_hook(tmp_path, {"tool_name": "mcp__delegate__ask_agy", "session_id": session_id, "cwd": cwd})

    logs = read_logs(tmp_path)
    assert len(logs) == 2
    for log in logs:
        assert log["project"] == "Uncle-J-s-Refinery"
        assert log["session"] == "055eceb3"
        assert "ts" in log
    assert logs[0]["decision"] == "allow"
    assert logs[1]["decision"] == "delegate"


def test_per_session_isolation(tmp_path):
    env = {"SELF_WORK_BUDGET": "1"}
    cwd = "/opt/proj/demo"

    # Session 1 makes 1 call (count=1)
    run_hook(tmp_path, {"tool_name": "Read", "session_id": "sess-one-1111", "cwd": cwd}, env)

    # Session 2 makes 1 call (count=1) -> allowed
    proc2 = run_hook(tmp_path, {"tool_name": "Write", "session_id": "sess-two-2222", "cwd": cwd}, env)
    assert proc2.returncode == 0
    assert proc2.stdout.strip() == ""

    # Session 1 makes 2nd call -> denied
    proc1_denied = run_hook(tmp_path, {"tool_name": "Read", "session_id": "sess-one-1111", "cwd": cwd}, env)
    assert proc1_denied.returncode == 0
    assert "deny" in proc1_denied.stdout

    # Session 2 makes its 1st retry / check: it hasn't exceeded yet, so 2nd call is denied only now
    proc2_denied = run_hook(tmp_path, {"tool_name": "Read", "session_id": "sess-two-2222", "cwd": cwd}, env)
    assert proc2_denied.returncode == 0
    assert "deny" in proc2_denied.stdout


def test_bad_json_fails_open(tmp_path):
    # Garbage string
    proc1 = run_hook(tmp_path, "not json at all {{{")
    assert proc1.returncode == 0
    assert proc1.stdout.strip() == ""

    # Empty string
    proc2 = run_hook(tmp_path, "")
    assert proc2.returncode == 0
    assert proc2.stdout.strip() == ""

    # Missing session_id or tool_name
    proc3 = run_hook(tmp_path, {"tool_name": "Read"})
    assert proc3.returncode == 0
    assert proc3.stdout.strip() == ""

    proc4 = run_hook(tmp_path, {"session_id": "sess-1"})
    assert proc4.returncode == 0
    assert proc4.stdout.strip() == ""


def test_unwritable_state_fails_open(tmp_path):
    # Point SELF_WORK_DIR to a file so mkdir fails
    blocker = tmp_path / "blocker_file"
    blocker.write_text("not a dir")
    env = {
        "SELF_WORK_DIR": str(blocker / "sub"),
        "SELF_WORK_LOG": str(blocker / "log.jsonl"),
        "SELF_WORK_BUDGET": "1",
    }
    payload = {"tool_name": "Read", "session_id": "sess-unwritable", "cwd": "/opt/proj/demo"}
    proc = run_hook(tmp_path, payload, env)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_parley_seat_project_normalized(tmp_path):
    session_id = "parley-sess-1"

    # Seats with random 8-char suffixes should be normalized to "parley-seat"
    run_hook(tmp_path, {"tool_name": "Read", "session_id": session_id, "cwd": "/tmp/parley-seat-a1b2c3d4"})
    run_hook(tmp_path, {"tool_name": "Read", "session_id": session_id, "cwd": "/tmp/parley-seat-99887766"})
    run_hook(tmp_path, {"tool_name": "Read", "session_id": session_id, "cwd": "/tmp/parley-seat-"})

    # Exact "parley-seat" should remain "parley-seat"
    run_hook(tmp_path, {"tool_name": "Read", "session_id": session_id, "cwd": "/opt/proj/parley-seat"})

    # Non-parley-seat directories should not be normalized
    run_hook(tmp_path, {"tool_name": "Read", "session_id": session_id, "cwd": "/opt/proj/my-parley-seat-foo"})
    run_hook(tmp_path, {"tool_name": "Read", "session_id": session_id, "cwd": "/opt/proj/Uncle-J-s-Refinery"})

    logs = read_logs(tmp_path)
    assert len(logs) == 6
    assert logs[0]["project"] == "parley-seat"
    assert logs[1]["project"] == "parley-seat"
    assert logs[2]["project"] == "parley-seat"
    assert logs[3]["project"] == "parley-seat"
    assert logs[4]["project"] == "my-parley-seat-foo"
    assert logs[5]["project"] == "Uncle-J-s-Refinery"


def test_log_rotation_over_5mb(tmp_path):
    log_file = tmp_path / ".claude" / "state" / "self-work.jsonl"
    log_file_1 = tmp_path / ".claude" / "state" / "self-work.jsonl.1"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. Over 5 MB triggers rotation: creates .1 (replacing old .1) and starts fresh log
    log_file_1.write_text('{"marker":"old_dot_one"}\n')
    size_5mb_plus = 5 * 1024 * 1024 + 100
    log_file.write_bytes(b"x" * size_5mb_plus)

    proc1 = run_hook(tmp_path, {"tool_name": "Read", "session_id": "sess-rot-1", "cwd": "/opt/proj/demo"})
    assert proc1.returncode == 0
    assert proc1.stdout.strip() == ""

    assert log_file_1.exists()
    assert log_file_1.stat().st_size == size_5mb_plus

    assert log_file.exists()
    lines = [json.loads(line) for line in log_file.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]["session"] == "sess-rot"

    # 2. Under 5 MB does not rotate: appends to existing log
    proc2 = run_hook(tmp_path, {"tool_name": "Write", "session_id": "sess-rot-2", "cwd": "/opt/proj/demo"})
    assert proc2.returncode == 0
    assert proc2.stdout.strip() == ""

    # .1 still has size from first rotation
    assert log_file_1.stat().st_size == size_5mb_plus
    # Live log now has 2 lines
    lines2 = [json.loads(line) for line in log_file.read_text().splitlines() if line.strip()]
    assert len(lines2) == 2


def test_prune_old_count_files(tmp_path):
    sw_dir = tmp_path / ".claude" / "state" / "self-work"
    sw_dir.mkdir(parents=True, exist_ok=True)

    old_count = sw_dir / "old-session-1.count"
    new_count = sw_dir / "new-session-2.count"
    other_old = sw_dir / "old-session-3.txt"

    old_count.write_text("5\n")
    new_count.write_text("3\n")
    other_old.write_text("keep me\n")

    now = time.time()
    t_8_days_ago = now - (8 * 86400)
    t_2_days_ago = now - (2 * 86400)

    os.utime(old_count, (t_8_days_ago, t_8_days_ago))
    os.utime(new_count, (t_2_days_ago, t_2_days_ago))
    os.utime(other_old, (t_8_days_ago, t_8_days_ago))

    proc = run_hook(tmp_path, {"tool_name": "Read", "session_id": "active-sess-xyz", "cwd": "/opt/proj/demo"})
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""

    # .count file older than 7 days is deleted
    assert not old_count.exists()
    # .count file within 7 days is preserved
    assert new_count.exists()
    # Non-.count file older than 7 days is preserved
    assert other_old.exists()
    # Active session count file was created/updated
    active_count = sw_dir / "active-sess-xyz.count"
    assert active_count.exists()


def test_rotation_failure_does_not_fail_hook(tmp_path):
    log_file = tmp_path / ".claude" / "state" / "self-work.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    # Make .1 a directory so mv fails
    log_file_1 = tmp_path / ".claude" / "state" / "self-work.jsonl.1"
    log_file_1.mkdir(parents=True, exist_ok=True)

    size_5mb_plus = 5 * 1024 * 1024 + 100
    log_file.write_bytes(b"x" * size_5mb_plus)

    proc = run_hook(tmp_path, {"tool_name": "Read", "session_id": "sess-rot-err", "cwd": "/opt/proj/demo"})
    # Hook must not fail or crash
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


@pytest.mark.parametrize("bash_cmd", [
    ".venv/bin/python scripts/ask_agy.py --prompt-file x.md --edits",
    "python3 scripts/ask_agy.py",
    "python scripts/ask_agy.py",
    "python scripts/referee.py --task 'review code'",
    ".venv/bin/python scripts/referee.py",
    "just agy 'review this diff'",
    "just agy",
])
def test_bash_delegation_commands_reset_counter(tmp_path, bash_cmd):
    env = {"SELF_WORK_BUDGET": "2"}
    session_id = "bash-delegation-session"
    cwd = "/opt/proj/Uncle-J-s-Refinery"

    # 2 tool calls to reach budget limit
    for tool in ("Read", "Bash"):
        proc = run_hook(
            tmp_path,
            {"tool_name": tool, "session_id": session_id, "cwd": cwd, "tool_input": {"command": "pwd"}},
            env,
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    count_file = tmp_path / ".claude" / "state" / "self-work" / f"{session_id}.count"
    assert count_file.read_text().strip() == "2"

    # Bash delegation command resets counter to 0 and logs 'delegate'
    proc_del = run_hook(
        tmp_path,
        {"tool_name": "Bash", "session_id": session_id, "cwd": cwd, "tool_input": {"command": bash_cmd}},
        env,
    )
    assert proc_del.returncode == 0
    assert proc_del.stdout.strip() == ""
    assert count_file.read_text().strip() == "0"

    logs = read_logs(tmp_path)
    assert len(logs) == 3
    assert logs[2]["decision"] == "delegate"
    assert logs[2]["tool"] == "Bash"

    # Next self-work calls should be allowed without hitting budget
    for tool in ("Grep", "Glob"):
        proc = run_hook(tmp_path, {"tool_name": tool, "session_id": session_id, "cwd": cwd}, env)
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    assert count_file.read_text().strip() == "2"


@pytest.mark.parametrize("bash_cmd", [
    "ls scripts/ask_agy.py",
    "cat scripts/ask_agy.py",
    "head -n 5 scripts/ask_agy.py",
    "ls scripts/referee.py",
    "cat scripts/referee.py",
    "just test",
])
def test_bash_unrelated_commands_stay_self_work(tmp_path, bash_cmd):
    env = {"SELF_WORK_BUDGET": "2"}
    session_id = "bash-self-work-session"
    cwd = "/opt/proj/Uncle-J-s-Refinery"

    # 1. First self-work call (count=1)
    proc1 = run_hook(
        tmp_path,
        {"tool_name": "Bash", "session_id": session_id, "cwd": cwd, "tool_input": {"command": bash_cmd}},
        env,
    )
    assert proc1.returncode == 0
    assert proc1.stdout.strip() == ""

    count_file = tmp_path / ".claude" / "state" / "self-work" / f"{session_id}.count"
    assert count_file.read_text().strip() == "1"

    # 2. Second self-work call (count=2)
    proc2 = run_hook(
        tmp_path,
        {"tool_name": "Bash", "session_id": session_id, "cwd": cwd, "tool_input": {"command": bash_cmd}},
        env,
    )
    assert proc2.returncode == 0
    assert proc2.stdout.strip() == ""
    assert count_file.read_text().strip() == "2"

    # 3. Third self-work call exceeds budget 2 -> denied
    proc3 = run_hook(
        tmp_path,
        {"tool_name": "Bash", "session_id": session_id, "cwd": cwd, "tool_input": {"command": bash_cmd}},
        env,
    )
    assert proc3.returncode == 0
    data = json.loads(proc3.stdout)
    assert data["hookSpecificOutput"]["permissionDecision"] == "deny"

    logs = read_logs(tmp_path)
    assert len(logs) == 3
    assert [l["decision"] for l in logs] == ["allow", "allow", "deny"]
    assert all(l["tool"] == "Bash" for l in logs)


# --- agy friction review 11-06, items G and the packet gap ---

def _local_only_env(tmp_path, budget="1"):
    roots = tmp_path / "local-only.txt"
    roots.write_text("# comment\n/opt/proj/secret-biz   # whole repo\n~/private-notes\n")
    return {"SELF_WORK_BUDGET": budget, "SELF_WORK_LOCAL_ONLY_FILE": str(roots)}


def _denied(proc):
    return proc.stdout.strip() != "" and json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_packet_tool_counts_as_delegation(tmp_path):
    env = {"SELF_WORK_BUDGET": "1"}
    base = {"session_id": "pkt-session-1", "cwd": "/opt/proj/x"}
    run_hook(tmp_path, {**base, "tool_name": "Read"}, env)
    run_hook(tmp_path, {**base, "tool_name": "mcp__delegate__ask_agy_packet"}, env)
    assert not _denied(run_hook(tmp_path, {**base, "tool_name": "Read"}, env))
    assert [r["decision"] for r in read_logs(tmp_path)][1] == "delegate"


def test_local_only_file_path_never_counted(tmp_path):
    env = _local_only_env(tmp_path)
    base = {"session_id": "lo-session-1", "cwd": "/opt/proj/Uncle-J-s-Refinery"}
    for _ in range(5):
        proc = run_hook(tmp_path, {**base, "tool_name": "Read",
                                   "tool_input": {"file_path": "/opt/proj/secret-biz/clients/a.md"}}, env)
        assert not _denied(proc)
    assert {r["decision"] for r in read_logs(tmp_path)} == {"local_only"}


def test_local_only_cwd_relative_path_and_tilde(tmp_path):
    env = _local_only_env(tmp_path)
    base = {"session_id": "lo-session-2", "cwd": "/opt/proj/secret-biz"}
    for _ in range(3):
        assert not _denied(run_hook(tmp_path, {**base, "tool_name": "Grep", "tool_input": {"path": "clients"}}, env))
    tilde = {"session_id": "lo-session-3", "cwd": "/opt/proj/x", "tool_name": "Read",
             "tool_input": {"file_path": str(tmp_path / "private-notes" / "n.md")}}
    for _ in range(3):
        assert not _denied(run_hook(tmp_path, tilde, env))


def test_local_only_named_in_bash_command(tmp_path):
    env = _local_only_env(tmp_path)
    base = {"session_id": "lo-session-4", "cwd": "/opt/proj/x", "tool_name": "Bash",
            "tool_input": {"command": "ls\nwc -l /opt/proj/secret-biz/notes.md"}}
    for _ in range(3):
        assert not _denied(run_hook(tmp_path, base, env))


def test_sibling_prefix_is_not_local_only(tmp_path):
    env = _local_only_env(tmp_path)
    base = {"session_id": "lo-session-5", "cwd": "/opt/proj/x", "tool_name": "Read",
            "tool_input": {"file_path": "/opt/proj/secret-biz2/a.md"}}
    run_hook(tmp_path, base, env)
    assert _denied(run_hook(tmp_path, base, env))


def test_missing_local_only_list_keeps_old_behaviour(tmp_path):
    env = {"SELF_WORK_BUDGET": "1", "SELF_WORK_LOCAL_ONLY_FILE": str(tmp_path / "nope.txt")}
    base = {"session_id": "lo-session-6", "cwd": "/opt/proj/secret-biz", "tool_name": "Read",
            "tool_input": {"file_path": "/opt/proj/secret-biz/a.md"}}
    run_hook(tmp_path, base, env)
    assert _denied(run_hook(tmp_path, base, env))

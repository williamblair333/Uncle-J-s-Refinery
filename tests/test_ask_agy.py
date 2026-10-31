"""Tests for scripts/ask_agy.py and features/antigravity/apply_permissions.py.

A fake `agy` replays a stream-json transcript, so no network or quota is used. The event
shapes are copied from real agy 1.3.5 runs (2026-10-15)."""
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ask = load("ask_agy", "scripts/ask_agy.py")
perms = load("apply_permissions", "features/antigravity/apply_permissions.py")


@pytest.mark.parametrize("cmd,fix", [
    # .venv is not a .env file, and a relative path is inside the repo (review, 2026-10-30)
    (".venv/bin/python -m pytest", 'add "command(.venv/bin/python)"'),
    ("sed -n 1p scripts/foo.py", 'add "command(sed)"'),
    ("git stash", 'add "command(git stash)"'),
    ("cat /etc/passwd", "ask Bill"),
    ("cat stack.env", "ask Bill"),
    ("printenv", "ask Bill"),
    ("cat /opt/proj/x/README.md", 'add "command(cat)"'),
])
def test_fix_cause_advice(cmd, fix):
    assert ask._compute_fix("RunCommand", cmd).startswith(fix)
sync = load("sync_mcp", "features/antigravity/sync_mcp.py")
rules_mod = load("install_rules", "features/antigravity/install_rules.py")


@pytest.fixture(autouse=True)
def _temp_delegate_log(tmp_path, monkeypatch):
    # main() logs to state/delegate.jsonl; tests must never write the real one (#229)
    log = tmp_path / "delegate-test.jsonl"
    monkeypatch.setenv("DELEGATE_LOG", str(log))
    denials_log = tmp_path / "agy-denials-test.jsonl"
    monkeypatch.setenv("AGY_DENIALS_LOG", str(denials_log))
    return log


def step(state, cmd="ls", error=None):
    info = {"name": "run_command", "parameters": {"CommandLine": cmd}}
    if error:
        info["error"] = {"type": "TOOL_ERROR", "message": error}
    return {"event": "step_update", "step_update": {"step_type": "tool", "tool_name": "run_command",
                                                     "state": state, "tool_info": info}}


def result(response, status="SUCCESS", denied=None):
    r = {"status": status, "response": response, "num_turns": 1}
    if denied:
        r["denied_actions"] = denied
    return {"event": "result", "result": r}


def fake_agy(tmp_path, events, exit_code=0, stderr=""):
    """Write an executable that prints `events` as JSON lines and records its argv."""
    data = tmp_path / "events.jsonl"
    data.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    argv_log = tmp_path / "argv.json"
    err_data = tmp_path / "stderr.txt"
    err_data.write_text(stderr)
    script = tmp_path / "agy"
    # Absolute interpreter: agy runs with features/antigravity/shims first on PATH, so
    # `env python3` would resolve to the python3 shim and need sandbox-run (not on CI).
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"json.dump(sys.argv[1:], open({str(argv_log)!r}, 'w'))\n"
        f"sys.stderr.write(open({str(err_data)!r}).read())\n"
        f"sys.stdout.write(open({str(data)!r}).read())\n"
        f"sys.exit({exit_code})\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script, argv_log


def run(tmp_path, events, *args, exit_code=0, stderr=""):
    script, argv_log = fake_agy(tmp_path, events, exit_code, stderr=stderr)
    outcome = ask.ask(*args or ("hello",), agy_bin=str(script), cwd=str(tmp_path))
    return outcome, json.loads(argv_log.read_text())


# ── ask_agy: success and the failure modes agy reports as SUCCESS ──────────

def test_clean_success(tmp_path):
    out, argv = run(tmp_path, [step("DONE"), result("the answer\n")])
    assert out["ok"] and out["response"] == "the answer"
    assert "--output-format" in argv and "stream-json" in argv


def test_hard_deny_is_failure_even_when_model_says_done(tmp_path):
    msg = "Permission denied for unsandboxed(ls; touch x). Matches user-configured deny rule."
    out, _ = run(tmp_path, [step("ERROR", "ls; touch x", msg), result("DONE\n")])
    assert not out["ok"]
    assert out["tool_errors"] and "deny rule" in out["tool_errors"][0]["message"]


def read_error(tool, message):
    return {"event": "step_update", "step_update": {
        "step_type": "tool", "tool_name": tool, "state": "ERROR",
        "tool_info": {"name": tool, "parameters": {"Path": "/x"}, "error": {"message": message}}}}


def test_recovered_lookup_error_is_success_with_warning(tmp_path):
    # 2026-10-27: a 603 s flash-high job wrote its full report and was marked failed for
    # a guessed path and a wrong MCP argument it had already worked around
    out, _ = run(tmp_path, [read_error("read_file", "file does not exist"),
                            read_error("call_mcp_tool", "'file_path' is a required property"),
                            result("the report\n")])
    assert out["ok"] and out["response"] == "the report"
    assert len(out["tool_errors"]) == 2 and "warning" in out


def test_denied_read_is_still_failure(tmp_path):
    msg = "permission check failed for read_file \"/home/x/.gemini/log\": Permission denied"
    out, _ = run(tmp_path, [read_error("read_file", msg), result("the report\n")])
    assert not out["ok"]


def test_failed_command_or_edit_is_still_failure(tmp_path):
    for tool in ("run_command", "edit_file"):
        out, _ = run(tmp_path, [read_error(tool, "target content not found"), result("DONE\n")])
        assert not out["ok"], tool


def test_lookup_error_with_empty_response_is_failure(tmp_path):
    out, _ = run(tmp_path, [read_error("read_file", "file does not exist"), result("")])
    assert not out["ok"]


def test_soft_deny_is_failure(tmp_path):
    out, _ = run(tmp_path, [result("", denied=[{"action": "command", "display_name": "RunCommand"}])])
    assert not out["ok"] and out["denied"] == ["RunCommand"]


def test_soft_deny_names_the_command(tmp_path):
    # the denied step ends DONE, not ERROR; denied_actions carries no command (2026-10-26 capture)
    cmd = "touch /tmp/agy-deny-probe.txt"
    out, _ = run(tmp_path, [step("ACTIVE", cmd), step("DONE", cmd),
                            result("", denied=[{"action": "command", "display_name": "RunCommand"}])])
    assert not out["ok"] and out["denied"] == ["RunCommand: touch /tmp/agy-deny-probe.txt"]


def test_soft_deny_without_command_line_shows_parameters(tmp_path):
    ev = {"event": "step_update", "step_update": {
        "step_index": 3, "step_type": "tool", "tool_name": "write_file", "state": "DONE",
        "tool_info": {"name": "write_file", "parameters": {"Path": "/x"}}}}
    out, _ = run(tmp_path, [ev, result("", denied=[{"action": "write"}])])
    assert not out["ok"] and len(out["denied"]) == 1 and '"Path"' in out["denied"][0]


def test_soft_deny_fix_cause_names_allow_rule(tmp_path):
    cmd = "git stash"
    out, _ = run(tmp_path, [step("ACTIVE", cmd), step("DONE", cmd),
                            result("", denied=[{"action": "command", "display_name": "RunCommand"}])])
    assert not out["ok"]
    assert "fix_cause" in out
    fixes = out["fix_cause"]
    assert len(fixes) == 1
    assert fixes[0]["tool"] == "RunCommand"
    assert fixes[0]["input"] == "git stash"
    assert fixes[0]["fix"] == 'add "command(git stash)" to allow in features/antigravity/permissions.json'


def test_deny_rule_tool_error_fix_cause(tmp_path):
    msg = "Permission denied for unsandboxed(just test). Matches user-configured deny rule."
    out, _ = run(tmp_path, [step("ERROR", "just test", msg), result("DONE\n")])
    assert not out["ok"]
    assert "fix_cause" in out
    fixes = out["fix_cause"]
    assert len(fixes) == 1
    assert fixes[0]["tool"] == "run_command"
    assert fixes[0]["input"] == "just test"
    assert fixes[0]["fix"] == 'add "command(just test)" to allow in features/antigravity/permissions.json'


def test_path_outside_opt_proj_asks_bill(tmp_path):
    cmd = "touch /tmp/probe.txt"
    out, _ = run(tmp_path, [step("ACTIVE", cmd), step("DONE", cmd),
                            result("", denied=[{"action": "command", "display_name": "RunCommand"}])])
    assert not out["ok"]
    assert "fix_cause" in out
    fixes = out["fix_cause"]
    assert len(fixes) == 1
    assert fixes[0]["input"] == "touch /tmp/probe.txt"
    assert fixes[0]["fix"] == "ask Bill before allowing: outside /opt/proj or secret-like"

    # Secret-like word
    out_sec = ask.fix_cause({"denied": ["RunCommand: cat .env"]})
    assert len(out_sec) == 1
    assert out_sec[0]["fix"] == "ask Bill before allowing: outside /opt/proj or secret-like"


def test_ok_with_warning_carries_fix_cause_only_when_deny_matched(tmp_path):
    # Lookup error without deny does not set fix_cause
    out1, _ = run(tmp_path, [read_error("read_file", "file does not exist"),
                             result("the report\n")])
    assert out1["ok"]
    assert "warning" in out1
    assert "fix the cause (see fix_cause) or file it" in out1["warning"]
    assert "fix_cause" not in out1

    # When fix_cause is computed on an ok dictionary, it carries fix_cause only if a deny matched
    out2 = {
        "ok": True,
        "tool_errors": [{"tool": "read_file", "input": '{"Path":"/opt/proj/x"}', "message": "permission check failed"}],
        "denied": []
    }
    causes = ask.fix_cause(out2)
    assert causes == [{"tool": "read_file", "input": '{"Path":"/opt/proj/x"}', "fix": "agy was refused read_file; check features/antigravity/permissions.json"}]


def test_log_denials_writes_and_disabled_by_empty_env(tmp_path, monkeypatch):
    log_file = tmp_path / "custom-denials.jsonl"
    monkeypatch.setenv("AGY_DENIALS_LOG", str(log_file))
    out = {
        "ok": False,
        "fix_cause": [
            {"tool": "RunCommand", "input": "git stash", "fix": 'add "command(git stash)" to allow in features/antigravity/permissions.json'}
        ]
    }
    ask.log_denials(out, "my-proj")
    assert log_file.is_file()
    lines = [json.loads(line) for line in log_file.read_text().splitlines() if line]
    assert len(lines) == 1
    assert lines[0]["project"] == "my-proj"
    assert lines[0]["tool"] == "RunCommand"
    assert lines[0]["input"] == "git stash"
    assert lines[0]["fix"] == 'add "command(git stash)" to allow in features/antigravity/permissions.json'
    assert isinstance(lines[0]["ts"], (int, float))

    # Empty env disables logging
    monkeypatch.setenv("AGY_DENIALS_LOG", "")
    log_file2 = tmp_path / "disabled-denials.jsonl"
    ask.log_denials(out, "my-proj", path=log_file2)
    assert not log_file2.exists()


def test_delegate_run_agy_logs_denials(tmp_path, monkeypatch):
    del_server = load("delegate_server", "scripts/delegate/server.py")
    denials_log = tmp_path / "agy-denials-del.jsonl"
    monkeypatch.setenv("AGY_DENIALS_LOG", str(denials_log))
    fake_ask = lambda *a, **kw: {
        "ok": False,
        "error": "headless mode auto-denied an action not on the allow list",
        "denied": ["RunCommand: git stash"],
        "fix_cause": [{"tool": "RunCommand", "input": "git stash", "fix": 'add "command(git stash)" to allow in features/antigravity/permissions.json'}]
    }
    del_server.run_agy("hello", cwd=str(tmp_path), ask=fake_ask, model="gemini-3.8-flash-medium")
    assert denials_log.is_file()
    lines = [json.loads(line) for line in denials_log.read_text().splitlines() if line]
    assert len(lines) == 1
    assert lines[0]["tool"] == "RunCommand"
    assert lines[0]["input"] == "git stash"
    assert lines[0]["project"] == tmp_path.name


def test_empty_response_is_failure(tmp_path):
    out, _ = run(tmp_path, [result("   \n")])
    assert not out["ok"] and "empty" in out["error"]


def test_non_success_status_is_failure(tmp_path):
    out, _ = run(tmp_path, [result("partial", status="ERROR")])
    assert not out["ok"]


def test_nonzero_exit_and_no_result_is_failure(tmp_path):
    out, _ = run(tmp_path, [{"event": "init"}], exit_code=3)
    assert not out["ok"] and "exit 3" in out["error"]


def test_conversation_id_captured_from_init(tmp_path):
    out, _ = run(tmp_path, [{"event": "init", "conversation_id": "conv-4d9b427c"}, result("ok")])
    assert out["ok"] and out["conversation_id"] == "conv-4d9b427c"


def test_conversation_id_captured_from_nested_init(tmp_path):
    out, _ = run(tmp_path, [{"event": "init", "init": {"conversation_id": "conv-nested-987"}}, result("ok")])
    assert out["ok"] and out["conversation_id"] == "conv-nested-987"


def test_edits_flag_and_timeout_passed(tmp_path):
    script, argv_log = fake_agy(tmp_path, [result("ok")])
    ask.ask("p", agy_bin=str(script), cwd=str(tmp_path), edits=True, timeout=42)
    argv = json.loads(argv_log.read_text())
    assert argv[argv.index("--mode") + 1] == "accept-edits"
    assert argv[argv.index("--print-timeout") + 1] == "42s"


def test_cli_exit_codes(tmp_path, capsys):
    script, _ = fake_agy(tmp_path, [result("fine")])
    assert ask.main(["--agy-bin", str(script), "--cwd", str(tmp_path), "q"]) == 0
    assert capsys.readouterr().out.strip() == "fine"
    script, _ = fake_agy(tmp_path, [result("", denied=[{"display_name": "RunCommand"}])])
    assert ask.main(["--agy-bin", str(script), "--cwd", str(tmp_path), "q"]) == 1
    assert json.loads(capsys.readouterr().err)["ok"] is False


def test_status_error_with_final_error_detail(tmp_path):
    r = {"status": "ERROR", "response": "", "error": "Individual quota reached. Resets in 2h0m0s"}
    out, _ = run(tmp_path, [{"event": "result", "result": r}])
    assert not out["ok"]
    assert out["error"] == "status ERROR"
    assert out["detail"] == "Individual quota reached. Resets in 2h0m0s"


def test_status_error_with_stderr_detail(tmp_path):
    r = {"status": "ERROR", "response": ""}
    stderr = "agent executor error: RESOURCE_EXHAUSTED: Resets in 5h"
    out, _ = run(tmp_path, [{"event": "result", "result": r}], stderr=stderr)
    assert not out["ok"]
    assert out["error"] == "status ERROR"
    assert out["detail"] == stderr


def test_status_error_with_tool_error_detail(tmp_path):
    msg = "edit_file: target content not found"
    tool_ev = step("ERROR", cmd="edit_file", error=msg)
    r = {"status": "ERROR", "response": ""}
    out, _ = run(tmp_path, [tool_ev, {"event": "result", "result": r}])
    assert not out["ok"]
    assert out["error"] == "status ERROR"
    assert out["detail"] == msg


def test_non_ok_branches_capture_stderr_detail(tmp_path):
    stderr = "warning: disk nearly full"
    out, _ = run(tmp_path, [result("   \n")], stderr=stderr)
    assert not out["ok"]
    assert out["detail"] == stderr


def test_tool_tally_and_mcp_attribution(tmp_path):
    events = [
        {"event": "step_update", "step_update": {"step_index": 1, "step_type": "tool", "tool_name": "run_command", "state": "ACTIVE"}},
        {"event": "step_update", "step_update": {"step_index": 1, "step_type": "tool", "tool_name": "run_command", "state": "DONE"}},
        {"event": "step_update", "step_update": {"step_index": 2, "step_type": "tool", "tool_name": "run_command", "state": "DONE"}},
        {"event": "step_update", "step_update": {"step_index": 3, "step_type": "tool", "tool_name": "call_mcp_tool", "state": "DONE",
                                                 "tool_info": {"parameters": {"ServerName": "jcodemunch", "ToolName": "search_symbols"}}}},
        {"event": "step_update", "step_update": {"step_index": 4, "step_type": "tool", "tool_name": "call_mcp_tool", "state": "DONE",
                                                 "tool_info": {"parameters": {}}}},
        result("done")
    ]
    out, _ = run(tmp_path, events)
    assert out["ok"]
    assert out["tools"] == {"run_command": 2, "mcp:jcodemunch": 1, "mcp": 1}


# ── apply_permissions: merge without clobbering agy's own keys ──────────────

def test_merge_keeps_other_keys_and_is_idempotent(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"trustedWorkspaces": ["/a"]}))
    rules = {"allow": ["command(ls)"], "deny": ["command(rm)"], "ask": []}
    assert perms.apply(settings, rules) is True
    data = json.loads(settings.read_text())
    assert data["trustedWorkspaces"] == ["/a"]
    assert data["permissions"]["allow"] == ["command(ls)"]
    assert oct(settings.stat().st_mode & 0o777) == "0o600"
    assert perms.apply(settings, rules) is False          # unchanged: no rewrite
    assert (tmp_path / "settings.json.bak").exists()


def test_merge_creates_missing_file(tmp_path):
    settings = tmp_path / "sub" / "settings.json"
    perms.apply(settings, {"allow": [], "deny": ["command(rm)"], "ask": []})
    assert json.loads(settings.read_text())["permissions"]["deny"] == ["command(rm)"]


def test_shipped_rules_have_no_wildcards_and_deny_destructive():
    rules = json.loads((REPO / "features/antigravity/permissions.json").read_text())
    # read_url(*) is the one catch-all: web research is what agy is for (Bill, 2026-10-25)
    joined = " ".join(r for r in rules["allow"] if r != "read_url(*)")
    assert "(*)" not in joined and "regex:" not in joined
    for must in ("command(rm)", "command(sudo)", "command(git push)", "command(curl)",
                 "mcp(jdocmunch/delete_index)", "mcp(jdatamunch/delete_dataset)"):
        assert must in rules["deny"]
    assert not set(rules["allow"]) & set(rules["deny"])
    # write-capable servers are never wholesale-allowed
    assert "mcp(serena/*)" not in rules["allow"] and "mcp(duckdb/*)" not in rules["allow"]


def test_read_only_lookups_are_allowed():
    # a Gemini job died on `which sandbox-run`, its first look at PATH (2026-10-26)
    rules = json.loads((REPO / "features/antigravity/permissions.json").read_text())
    for cmd in ("which", "basename", "dirname", "realpath", "readlink", "date", "sleep", "ps", "local-health"):
        assert f"command({cmd})" in rules["allow"]
    assert "command(git grep)" not in rules["allow"]
    assert "command(git grep -O)" in rules["deny"]
    assert "command(git grep --open-files-in-pager)" in rules["deny"]
    assert "command(grep)" in rules["allow"] and "command(rg)" in rules["allow"]
    # no echo: a redirect (`echo x > f`) would write, and the matcher isn't known to refuse it
    assert "command(echo)" not in rules["allow"]


# ── sync_mcp: Claude user-scope servers -> agy mcp_config.json ───────────────

def test_sync_mcp_copies_servers_keeps_others_and_is_private(tmp_path):
    claude = tmp_path / ".claude.json"
    claude.write_text(json.dumps({"mcpServers": {
        "jcodemunch": {"type": "stdio", "command": "/v/jcodemunch-mcp", "args": [], "env": {}},
        "context7": {"command": "npx", "args": ["-y", "c7"], "env": {"CONTEXT7_API_KEY": "k"}},
        "remote": {"type": "http", "url": "https://x/mcp", "headers": {"A": "b"}},
    }, "other": 1}))
    target = tmp_path / "config" / "mcp_config.json"
    target.parent.mkdir()
    target.write_text("")                                      # agy ships it empty
    assert sync.sync(claude, target) == ["context7", "jcodemunch", "remote"]
    data = json.loads(target.read_text())["mcpServers"]
    assert data["jcodemunch"] == {"command": "/v/jcodemunch-mcp", "args": []}
    assert data["context7"]["env"] == {"CONTEXT7_API_KEY": "k"}
    assert data["remote"] == {"url": "https://x/mcp", "headers": {"A": "b"}}
    assert oct(target.stat().st_mode & 0o777) == "0o600"
    # a server added on the agy side survives a re-sync
    d = json.loads(target.read_text()); d["mcpServers"]["mine"] = {"command": "x"}
    target.write_text(json.dumps(d))
    sync.sync(claude, target)
    assert "mine" in json.loads(target.read_text())["mcpServers"]


# ── install_rules: marker-delimited block in a user-owned rules file ─────────

def test_rules_block_appends_then_replaces_only_its_block(tmp_path):
    target = tmp_path / "GEMINI.md"
    target.write_text("# Global Personal Memory\n\n- keep me\n")
    rules_mod.install(target, "<!-- S -->\nv1\n<!-- E -->", "<!-- S -->", "<!-- E -->")
    rules_mod.install(target, "<!-- S -->\nv2\n<!-- E -->", "<!-- S -->", "<!-- E -->")
    text = target.read_text()
    assert text.startswith("# Global Personal Memory\n\n- keep me\n")
    assert "v2" in text and "v1" not in text and text.count("<!-- S -->") == 1
    assert (tmp_path / "GEMINI.md.bak").exists()


def test_shipped_rules_block_includes_claude_md_and_fits():
    block = (REPO / "features/antigravity/rules-block.md").read_text()
    assert "@[" in block and "CLAUDE.md)" in block
    assert len((REPO / "CLAUDE.md").read_bytes()) + len(block.encode()) < 24_000  # agy per-file cap


def test_sync_mcp_never_gives_agy_delegate(tmp_path):
    # delegate's ask_agy inside agy would let agy call itself
    claude = tmp_path / "claude_user.json"
    claude.write_text(json.dumps({"mcpServers": {
        "delegate": {"command": "/v/python", "args": ["delegate/server.py"]},
        "memweave": {"command": "/v/python", "args": ["mw_mcp.py"]},
    }}))
    target = tmp_path / "mcp_config.json"
    target.write_text(json.dumps({"mcpServers": {"delegate": {"command": "old"}}}))
    assert sync.sync(claude, target) == ["memweave"]
    assert set(json.loads(target.read_text())["mcpServers"]) == {"memweave"} | set(sync.AGY_EXTRA)


def test_sync_mcp_always_gives_agy_a_pinned_fetch_server(tmp_path):
    # headless agy has no web tool of its own (read_url isn't registered in print mode)
    claude = tmp_path / "claude_user.json"
    claude.write_text(json.dumps({"mcpServers": {}}))
    target = tmp_path / "mcp_config.json"
    sync.sync(claude, target)
    fetch = json.loads(target.read_text())["mcpServers"]["fetch"]
    assert fetch["command"] == "uvx" and fetch["args"][0].startswith("mcp-server-fetch==")
    assert "--allow-private-ips" not in fetch["args"]
    rules = json.loads((REPO / "features/antigravity/permissions.json").read_text())
    assert "mcp(fetch/*)" in rules["allow"]


# ── shims: sandboxed habitual commands ──────────────────────────────────────

def test_shimmed_pytest_resolves_to_local_venv(tmp_path):
    if shutil.which("bwrap") is None:
        pytest.skip("bubblewrap not installed")
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    fake_pytest = venv_bin / "pytest"
    fake_pytest.write_text("#!/bin/sh\necho 'local-venv-pytest'\n")
    fake_pytest.chmod(fake_pytest.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)

    sandbox_dir = REPO / "features" / "antigravity"
    shims_dir = sandbox_dir / "shims"

    # Simulate running outside sandbox (where /run/sandbox-run-inside does not exist).
    # If the test runner is itself in a sandbox, mask /run with a tmpfs so the shim
    # executes its outside-sandbox branch (exec sandbox-run pytest).
    run_marker = Path("/run/sandbox-run-inside")
    if run_marker.exists():
        cmd = [
            "bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
            "--tmpfs", "/run", "--bind", str(tmp_path), str(tmp_path),
            "--chdir", str(tmp_path),
            "--setenv", "PATH", f"{shims_dir}:{sandbox_dir}:{os.environ['PATH']}",
            "pytest",
        ]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    else:
        env = {**os.environ, "PATH": f"{shims_dir}:{sandbox_dir}:{os.environ['PATH']}"}
        out = subprocess.run(["pytest"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)

    assert out.returncode == 0
    assert out.stdout.strip() == "local-venv-pytest"


def test_shimmed_command_never_reenters_shim(tmp_path):
    if shutil.which("bwrap") is None:
        pytest.skip("bubblewrap not installed")
    sandbox_script = REPO / "features" / "antigravity" / "sandbox-run"
    shims_dir = REPO / "features" / "antigravity" / "shims"

    # Inside sandbox-run with shims first on PATH:
    # 1. Python executes system python directly, not re-invoking the shim
    check_code = (
        "import os, sys; "
        f"shim = {str(shims_dir / 'python3')!r}; "
        "assert os.path.realpath(sys.executable) != os.path.realpath(shim); "
        "print('direct-exec')"
    )
    cmd = f"PATH={shims_dir}:$PATH python3 -c {check_code!r}"
    out = subprocess.run(["bash", str(sandbox_script), "sh", "-c", cmd],
                         cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0
    assert out.stdout.strip() == "direct-exec"

    # 2. Inside sandbox, a shimmed tool finds the next binary on PATH and does not recurse
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_tool = bin_dir / "pytest"
    fake_tool.write_text("#!/bin/sh\necho 'real-binary'\n")
    fake_tool.chmod(fake_tool.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)

    cmd2 = f"PATH={shims_dir}:{bin_dir}:$PATH pytest"
    out2 = subprocess.run(["bash", str(sandbox_script), "sh", "-c", cmd2],
                          cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert out2.returncode == 0
    assert out2.stdout.strip() == "real-binary"


# ── agy's own --print-timeout: name it, never file it under tool errors ───────
# 2026-10-26: two 20-minute timeouts were logged as "a tool call failed", so
# `just offload` counted them as tool failures and nobody looked at them.

TIMEOUT_STDERR = "poll.go:188: Print mode: print timeout after 20m0s\n"


def test_print_timeout_with_lookup_error_is_named(tmp_path):
    out, _ = run(tmp_path, [read_error("read_file", "file does not exist"), result("")],
                 stderr=TIMEOUT_STDERR)
    assert not out["ok"] and "print timeout" in out["error"]


def test_print_timeout_with_partial_response_is_failure(tmp_path):
    out, _ = run(tmp_path, [step("DONE"), result("half a report\n")], stderr=TIMEOUT_STDERR)
    assert not out["ok"] and "print timeout" in out["error"]


def test_print_timeout_without_result_event_is_named(tmp_path):
    out, _ = run(tmp_path, [step("DONE")], exit_code=1, stderr=TIMEOUT_STDERR)
    assert not out["ok"] and "print timeout" in out["error"]


# ── CLI runs land in delegate.jsonl so `just offload` counts them ─────────────
# 2026-10-29: every agy job of 10-28/10-29 ran from Bash and the report never saw it.

def read_log(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_cli_success_is_logged(tmp_path, _temp_delegate_log):
    script, _ = fake_agy(tmp_path, [result("fine")])
    ask.main(["--agy-bin", str(script), "--cwd", str(tmp_path), "--model", "m1", "q"])
    (rec,) = read_log(_temp_delegate_log)
    assert rec["backend"] == "agy" and rec["model"] == "m1" and rec["ok"] is True
    assert rec["via"] == "cli" and rec["project"] == tmp_path.name
    assert isinstance(rec["seconds"], float) and "error" not in rec


def test_cli_failure_is_logged_with_error(tmp_path, _temp_delegate_log):
    script, _ = fake_agy(tmp_path, [result("")])
    ask.main(["--agy-bin", str(script), "--cwd", str(tmp_path), "q"])
    (rec,) = read_log(_temp_delegate_log)
    assert rec["ok"] is False and rec["error"] == "empty response"
    assert rec["model"] == "agy-default"


def test_cli_log_disabled_by_empty_env(tmp_path, monkeypatch, _temp_delegate_log):
    monkeypatch.setenv("DELEGATE_LOG", "")
    script, _ = fake_agy(tmp_path, [result("fine")])
    assert ask.main(["--agy-bin", str(script), "--cwd", str(tmp_path), "q"]) == 0
    assert not _temp_delegate_log.exists()


def test_library_ask_does_not_log(tmp_path, _temp_delegate_log):
    # the delegate server calls ask() and logs itself; logging there too would double-count
    run(tmp_path, [result("fine")])
    assert not _temp_delegate_log.exists()

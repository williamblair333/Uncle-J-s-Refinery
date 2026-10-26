"""Tests for scripts/ask_agy.py and features/antigravity/apply_permissions.py.

A fake `agy` replays a stream-json transcript, so no network or quota is used. The event
shapes are copied from real agy 1.3.5 runs (2026-10-15)."""
import importlib.util
import json
import os
import stat
from pathlib import Path

REPO = Path(__file__).parent.parent


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ask = load("ask_agy", "scripts/ask_agy.py")
perms = load("apply_permissions", "features/antigravity/apply_permissions.py")
sync = load("sync_mcp", "features/antigravity/sync_mcp.py")
rules_mod = load("install_rules", "features/antigravity/install_rules.py")


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
    script.write_text(
        "#!/usr/bin/env python3\n"
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

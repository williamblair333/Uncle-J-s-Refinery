"""Tests for scripts/delegate/server.py. No network, agy, GPU or quota is used."""
import importlib.util
import io
import json
import os
import time
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent


def load():
    spec = importlib.util.spec_from_file_location("delegate_server", REPO / "scripts/delegate/server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


d = load()

AGY_ONLY = {"default": "code", "tiers": {
    "light": ["gemini-3.8-flash-low", "gpt-oss-120b-medium"],
    "code": ["gemini-3.8-flash-medium"], "hard": ["claude-opus-5-5-high"]}}


@pytest.fixture(autouse=True)
def routing(tmp_path, monkeypatch):
    """Tests own the routing file, and no test reaches a real local model."""
    f = tmp_path / "routing.json"
    f.write_text(json.dumps(AGY_ONLY))
    monkeypatch.setattr(d, "ROUTING_FILE", f)
    monkeypatch.setenv("ASK_LOCAL_LOG", str(tmp_path / "ask_local.jsonl"))

    def no_network(prompt):
        raise AssertionError("real local backend called")
    monkeypatch.setattr(d, "_heretic_raw", no_network)
    monkeypatch.setattr(d, "run_ask_local", no_network)
    return f


def test_roots_file_and_env(tmp_path):
    f = tmp_path / "lo.txt"
    f.write_text("# comment\n/opt/secret   # trailing\n\n")
    roots = d.local_only_roots(f, env=f"{tmp_path}/a:")
    assert roots == [Path("/opt/secret").resolve(), (tmp_path / "a").resolve()]


def test_block_on_cwd_and_children(tmp_path):
    roots = [tmp_path / "priv"]
    assert d.local_only_block(str(tmp_path / "priv"), roots=roots)
    assert d.local_only_block(str(tmp_path / "priv/sub"), roots=roots)
    assert d.local_only_block(str(tmp_path / "private2"), roots=roots) is None


def test_block_on_path_in_prompt(tmp_path):
    roots = [tmp_path / "priv"]
    prompt = f"summarize `{tmp_path}/priv/fig1.step`, please"
    assert d.local_only_block(str(tmp_path), prompt, roots=roots) == str(roots[0])
    assert d.local_only_block(str(tmp_path), f"read {tmp_path}/pub/x", roots=roots) is None
    assert d.local_only_block(str(tmp_path), f"what is in {tmp_path}/priv?", roots=roots)
    assert d.local_only_block(str(tmp_path), f"look at {tmp_path}/priv.", roots=roots)


def test_agy_refuses_local_only_without_calling(tmp_path, monkeypatch):
    monkeypatch.setenv("DELEGATE_LOCAL_ONLY", str(tmp_path))
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    called = []
    out = d.run_agy("hi", cwd=str(tmp_path), ask=lambda *a, **k: called.append(1))
    assert out["error"] == "local_only" and not called


def test_agy_passes_model_and_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setenv("DELEGATE_LOCAL_ONLY", "")
    monkeypatch.setattr(d, "LOG_PATH", tmp_path / "log.jsonl")
    monkeypatch.setattr(d, "QUOTA_PATH", tmp_path / "quota.json")
    seen = {}

    def fake(prompt, **kw):
        seen.update(kw)
        return {"ok": False, "response": "", "tool_errors": [], "denied": [], "error": "status ERROR"}

    out = d.run_agy("hi", cwd=str(tmp_path), model=d.AGY_MODEL, ask=fake)
    assert seen["model"] == d.AGY_MODEL and seen["cwd"] == str(tmp_path)
    assert out["ok"] is False and "quota" in out["hint"] and "response" not in out
    rec = json.loads((tmp_path / "log.jsonl").read_text())
    assert rec["backend"] == "agy" and rec["ok"] is False and "hi" not in json.dumps(rec)


def test_openai_not_configured(monkeypatch):
    monkeypatch.delenv(d.OPENAI_KEY_ENV, raising=False)
    assert d.run_openai("hi", model="m")["error"] == "not_configured"


def test_openai_success(tmp_path, monkeypatch):
    monkeypatch.setenv(d.OPENAI_KEY_ENV, "k")
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setenv("DELEGATE_LOCAL_ONLY", "")
    monkeypatch.setattr(d, "LOG_PATH", None)
    sent = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout):
        sent["auth"] = req.headers["Authorization"]
        sent["body"] = json.loads(req.data)
        return Resp(json.dumps({"choices": [{"message": {"content": " yes "}}]}).encode())

    out = d.run_openai("hi", system="s", model="m", cwd=str(tmp_path), opener=opener)
    assert out == {"ok": True, "text": "yes", "usage": None, "model": "m"}
    assert sent["auth"] == "Bearer k" and sent["body"]["messages"][0]["role"] == "system"


def test_local_chat_loaded_lazily():
    assert d._local_chat is None


def test_tier_walk_order(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "QUOTA_PATH", tmp_path / "quota.json")
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setattr(d, "LOG_PATH", None)
    calls = []

    def fake(prompt, **kw):
        m = kw.get("model")
        calls.append(m)
        if m == "gemini-3.8-flash-low":
            return {"ok": False, "error": "status ERROR", "response": "quota exhausted"}
        return {"ok": True, "response": "done"}

    out = d.run_agy("hi", task="light", cwd=str(tmp_path), ask=fake)
    assert calls == ["gemini-3.8-flash-low", "gpt-oss-120b-medium"]
    assert out["ok"] is True
    assert out["model"] == "gpt-oss-120b-medium"
    assert out["skipped"] == [{"model": "gemini-3.8-flash-low", "reason": "quota exhausted"}]


def test_skips_model_marked_exhausted(tmp_path, monkeypatch):
    quota_file = tmp_path / "quota.json"
    quota_file.write_text(json.dumps({"gemini-3.8-flash-low": time.time() + 3600}))
    monkeypatch.setattr(d, "QUOTA_PATH", quota_file)
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setattr(d, "LOG_PATH", None)
    calls = []

    def fake(prompt, **kw):
        calls.append(kw.get("model"))
        return {"ok": True, "response": "done"}

    out = d.run_agy("hi", task="light", cwd=str(tmp_path), ask=fake)
    assert calls == ["gpt-oss-120b-medium"]
    assert out["ok"] is True
    assert out["model"] == "gpt-oss-120b-medium"
    assert len(out["skipped"]) == 1
    assert out["skipped"][0]["model"] == "gemini-3.8-flash-low"
    assert "exhausted until" in out["skipped"][0]["reason"]


def test_exhaustion_recorded_with_parsed_reset_time(tmp_path, monkeypatch):
    quota_file = tmp_path / "quota.json"
    monkeypatch.setattr(d, "QUOTA_PATH", quota_file)
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setattr(d, "LOG_PATH", None)
    now = 1700000000.0
    monkeypatch.setattr(time, "time", lambda: now)

    def fake(prompt, **kw):
        m = kw.get("model")
        if m == "gemini-3.8-flash-low":
            return {"ok": False, "error": "status ERROR", "response": "Resource exhausted. Resets in 2h30m15s"}
        return {"ok": True, "response": "done"}

    out = d.run_agy("hi", task="light", cwd=str(tmp_path), ask=fake)
    assert out["ok"] is True
    quota = json.loads(quota_file.read_text())
    # 2h (7200) + 30m (1800) + 15s (15) = 9015
    assert quota["gemini-3.8-flash-low"] == now + 9015


def test_explicit_model_bypasses_tiers(tmp_path, monkeypatch):
    quota_file = tmp_path / "quota.json"
    quota_file.write_text(json.dumps({"custom-model": time.time() + 3600}))
    monkeypatch.setattr(d, "QUOTA_PATH", quota_file)
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setattr(d, "LOG_PATH", None)
    calls = []

    def fake(prompt, **kw):
        calls.append(kw.get("model"))
        return {"ok": True, "response": "done"}

    out = d.run_agy("hi", model="custom-model", task="light", cwd=str(tmp_path), ask=fake)
    assert calls == ["custom-model"]
    assert out["ok"] is True
    assert out["model"] == "custom-model"
    assert "skipped" not in out


def test_all_exhausted_error(tmp_path, monkeypatch):
    quota_file = tmp_path / "quota.json"
    monkeypatch.setattr(d, "QUOTA_PATH", quota_file)
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setattr(d, "LOG_PATH", None)

    def fake(prompt, **kw):
        return {"ok": False, "error": "status ERROR", "response": "quota exhausted"}

    out = d.run_agy("hi", task="light", cwd=str(tmp_path), ask=fake)
    assert out["ok"] is False
    assert out["error"] == "all models in tier light exhausted"
    assert len(out["skipped"]) == 2
    assert "hint" in out


def test_status_shows_agy_models(tmp_path, monkeypatch):
    quota_file = tmp_path / "quota.json"
    now = 1700000000.0
    monkeypatch.setattr(time, "time", lambda: now)
    quota_file.write_text(json.dumps({"gemini-3.8-flash-low": now + 3600}))
    monkeypatch.setattr(d, "QUOTA_PATH", quota_file)

    st = d.status()
    assert "agy_models" in st
    assert "tiers" in st["agy_models"]
    assert "exhausted" in st["agy_models"]
    assert st["agy_models"]["tiers"]["light"] == "gpt-oss-120b-medium"
    assert "gemini-3.8-flash-low" in st["agy_models"]["exhausted"]


# ── light tier: free local models first ──────────────────────────────────────

def with_locals(routing, monkeypatch, tmp_path):
    cfg = json.loads(routing.read_text())
    cfg["tiers"]["light"] = ["local:heretic", "local:ask_local"] + cfg["tiers"]["light"]
    routing.write_text(json.dumps(cfg))
    monkeypatch.setattr(d, "QUOTA_PATH", tmp_path / "quota.json")
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setenv("DELEGATE_LOCAL_ONLY", "")
    monkeypatch.setattr(d, "LOG_PATH", None)
    calls = []

    def agy(prompt, **kw):
        calls.append(kw["model"])
        return {"ok": True, "response": "agy"}
    return calls, agy


def locals_(heretic, ask_local):
    return {"local:heretic": lambda p: heretic, "local:ask_local": lambda p: ask_local}


def test_light_tries_heretic_first(routing, monkeypatch, tmp_path):
    calls, agy = with_locals(routing, monkeypatch, tmp_path)
    out = d.run_agy("hi", task="light", cwd=str(tmp_path), ask=agy,
                    local=locals_({"ok": True, "text": " yes "}, {"text": "no"}))
    assert out == {"ok": True, "response": "yes", "model": "local:heretic"} and not calls


@pytest.mark.parametrize("prompt,edits", [("summarize /opt/proj/x.py", False), ("hi", True)])
def test_light_skips_locals_for_files_and_edits(routing, monkeypatch, tmp_path, prompt, edits):
    calls, agy = with_locals(routing, monkeypatch, tmp_path)
    out = d.run_agy(prompt, task="light", cwd=str(tmp_path), ask=agy, edits=edits,
                    local=locals_({"ok": True, "text": "x"}, {"text": "x"}))
    assert calls == ["gemini-3.8-flash-low"] and out["model"] == "gemini-3.8-flash-low"
    assert [s["model"] for s in out["skipped"]] == ["local:heretic", "local:ask_local"]
    assert all(s["reason"] == d._LOCAL_CANNOT for s in out["skipped"])


def test_light_falls_through_failed_locals(routing, monkeypatch, tmp_path):
    calls, agy = with_locals(routing, monkeypatch, tmp_path)
    out = d.run_agy("hi", task="light", cwd=str(tmp_path), ask=agy,
                    local=locals_({"ok": False, "error": "heretic unreachable"}, {"text": "ok"}))
    assert out["model"] == "local:ask_local" and not calls
    assert out["skipped"] == [{"model": "local:heretic", "reason": "heretic unreachable"}]
    out = d.run_agy("hi", task="light", cwd=str(tmp_path), ask=agy,
                    local=locals_({"ok": True, "text": "  "}, {"error": "ollama_unreachable"}))
    assert calls == ["gemini-3.8-flash-low"] and out["response"] == "agy"
    assert out["skipped"][0]["reason"] == "empty response"


def test_local_only_runs_locals_never_agy(routing, monkeypatch, tmp_path):
    calls, agy = with_locals(routing, monkeypatch, tmp_path)
    monkeypatch.setenv("DELEGATE_LOCAL_ONLY", str(tmp_path))
    out = d.run_agy("hi", task="light", cwd=str(tmp_path), ask=agy,
                    local=locals_({"ok": True, "text": "private"}, {}))
    assert out["model"] == "local:heretic" and not calls
    out = d.run_agy("hi", task="light", cwd=str(tmp_path), ask=agy,
                    local=locals_({"ok": False, "error": "down"}, {"error": "down"}))
    assert out["error"] == "local_only" and not calls
    assert d.run_agy("hi", task="code", cwd=str(tmp_path), ask=agy)["error"] == "local_only"
    assert not calls


def test_is_exhausted_cases():
    assert d._is_exhausted({"ok": False, "error": "status ERROR", "detail": "RESOURCE_EXHAUSTED (code 429)"}) is True
    assert d._is_exhausted({"ok": False, "error": "status ERROR", "detail": "Individual quota reached. Resets in 2h"}) is True
    assert d._is_exhausted({"ok": False, "error": "status ERROR", "response": "", "usage": {"total_tokens": 0}}) is True
    assert d._is_exhausted({"ok": False, "error": "status ERROR", "response": "", "usage": {"total_tokens": 15}}) is False
    assert d._is_exhausted({"ok": True, "response": "quota"}) is False


def test_exhaustion_individual_quota_with_detail_records_7200s(tmp_path, monkeypatch):
    quota_file = tmp_path / "quota.json"
    monkeypatch.setattr(d, "QUOTA_PATH", quota_file)
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setattr(d, "LOG_PATH", None)
    now = 1700000000.0
    monkeypatch.setattr(time, "time", lambda: now)

    def fake(prompt, **kw):
        m = kw.get("model")
        if m == "gemini-3.8-flash-low":
            return {"ok": False, "error": "status ERROR", "detail": "Individual quota reached. Resets in 2h0m0s", "response": ""}
        return {"ok": True, "response": "done"}

    out = d.run_agy("hi", task="light", cwd=str(tmp_path), ask=fake)
    assert out["ok"] is True
    quota = json.loads(quota_file.read_text())
    assert quota["gemini-3.8-flash-low"] == now + 7200


def test_log_records_tools_counts_when_present(tmp_path, monkeypatch):
    log_file = tmp_path / "log.jsonl"
    monkeypatch.setattr(d, "LOG_PATH", log_file)
    d._log("agy", "gemini-3.8-flash-low", time.time() - 1,
           {"ok": True, "response": "done", "tools": {"run_command": 2, "mcp:jcodemunch": 1}})
    lines = [json.loads(line) for line in log_file.read_text().splitlines()]
    assert len(lines) == 1
    assert lines[0]["tools"] == {"run_command": 2, "mcp:jcodemunch": 1}
    assert lines[0]["project"] == os.path.basename(os.getcwd())


def test_log_records_project_from_callers(tmp_path, monkeypatch):
    log_file = tmp_path / "log.jsonl"
    monkeypatch.setattr(d, "LOG_PATH", log_file)
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setenv("DELEGATE_LOCAL_ONLY", "")

    custom_cwd = tmp_path / "sample_project"
    custom_cwd.mkdir()

    # 1. Direct _log with cwd
    d._log("test_backend", "m", time.time() - 1, {"ok": True}, cwd=str(custom_cwd))

    # 2. run_agy passing cwd
    d.run_agy("hi", cwd=str(custom_cwd), model="gemini-3.8-flash-low",
              ask=lambda *a, **k: {"ok": True, "response": "ok"})

    # 3. run_heretic passing cwd
    monkeypatch.setattr(d, "_heretic_raw", lambda *a, **k: {"ok": True, "text": "heretic ok"})
    d.run_heretic("hi", cwd=str(custom_cwd))

    # 4. run_openai passing cwd
    monkeypatch.setenv(d.OPENAI_KEY_ENV, "k")
    monkeypatch.setattr(d, "OPENAI_MODEL", "m")

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    d.run_openai("hi", model="m", cwd=str(custom_cwd),
                 opener=lambda req, timeout: Resp(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()))

    lines = [json.loads(line) for line in log_file.read_text().splitlines()]
    assert len(lines) == 4
    for line in lines:
        assert line["project"] == "sample_project"


def test_agy_log_copy_and_pruning(tmp_path, monkeypatch):
    src_dir = tmp_path / "src_logs"
    src_dir.mkdir()
    dest_dir = tmp_path / "dest_logs"
    dest_dir.mkdir()
    monkeypatch.setenv("DELEGATE_AGY_LOG_SRC", str(src_dir))
    monkeypatch.setenv("DELEGATE_AGY_LOG_DIR", str(dest_dir))
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setattr(d, "LOG_PATH", None)

    # Pre-populate dest_dir with 52 logs to test pruning to 50
    for i in range(52):
        old_log = dest_dir / f"20261025-0000{i:02d}-old.log"
        old_log.write_text(f"old log {i}")
        t = 1000.0 + i
        os.utime(old_log, (t, t))

    assert len(list(dest_dir.glob("*.log"))) == 52

    t0 = time.time()
    old_src = src_dir / "cli-20261025_000000.log"
    old_src.write_text("before call")
    os.utime(old_src, (t0 - 100, t0 - 100))

    src_log1 = src_dir / "cli-20261026_120000.log"
    src_log1.write_text("first new")
    os.utime(src_log1, (t0 + 10, t0 + 10))

    src_log2 = src_dir / "cli-20261026_120001.log"
    src_log2.write_text("second newest")
    os.utime(src_log2, (t0 + 20, t0 + 20))

    def fake_fail(prompt, **kw):
        return {"ok": False, "error": "status ERROR", "response": ""}

    out = d.run_agy("hi", model="gemini-3.8-flash-low", cwd=str(tmp_path), ask=fake_fail)
    assert not out["ok"]
    assert "log" in out
    log_path = Path(out["log"])
    assert log_path.exists()
    assert log_path.read_text() == "second newest"

    # Verify pruned to 50
    dest_files = list(dest_dir.glob("*.log"))
    assert len(dest_files) == 50
    assert log_path in dest_files


def test_agy_log_copy_prefers_matching_conversation_id(tmp_path, monkeypatch):
    src_dir = tmp_path / "src_logs"
    src_dir.mkdir()
    dest_dir = tmp_path / "dest_logs"
    dest_dir.mkdir()
    monkeypatch.setenv("DELEGATE_AGY_LOG_SRC", str(src_dir))
    monkeypatch.setenv("DELEGATE_AGY_LOG_DIR", str(dest_dir))
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setattr(d, "LOG_PATH", None)

    t0 = time.time()
    src_log1 = src_dir / "cli-20261026_120000.log"
    src_log1.write_text("session 1 conv-aaa-111 content")
    os.utime(src_log1, (t0 + 10, t0 + 10))

    src_log2 = src_dir / "cli-20261026_120001.log"
    src_log2.write_text("session 2 conv-bbb-222 content")
    os.utime(src_log2, (t0 + 20, t0 + 20))

    # Match older candidate by conversation_id
    def fake_fail_matching(prompt, **kw):
        return {"ok": False, "error": "status ERROR", "response": "", "conversation_id": "conv-aaa-111"}

    out = d.run_agy("hi", model="gemini-3.8-flash-low", cwd=str(tmp_path), ask=fake_fail_matching)
    assert not out["ok"]
    assert "log" in out
    assert Path(out["log"]).read_text() == "session 1 conv-aaa-111 content"

    # Fall back to newest when conversation_id doesn't match
    def fake_fail_unmatched(prompt, **kw):
        return {"ok": False, "error": "status ERROR", "response": "", "conversation_id": "conv-unknown"}

    out2 = d.run_agy("hi", model="gemini-3.8-flash-low", cwd=str(tmp_path), ask=fake_fail_unmatched)
    assert not out2["ok"]
    assert "log" in out2
    assert Path(out2["log"]).read_text() == "session 2 conv-bbb-222 content"


def test_local_result_preserves_usage_and_hint():
    raw_ok = {"ok": True, "text": "answer", "usage": {"total_tokens": 42}, "hint": "useful hint"}
    res_ok = d._local_result("local:heretic", raw_ok)
    assert res_ok["ok"] is True
    assert res_ok["response"] == "answer"
    assert res_ok["usage"] == {"total_tokens": 42}
    assert res_ok["hint"] == "useful hint"

    raw_err = {"ok": False, "error": "failed", "detail": "more info", "usage": {"total_tokens": 5}, "hint": "boot it"}
    res_err = d._local_result("local:heretic", raw_err)
    assert res_err["ok"] is False
    assert res_err["error"] == "failed: more info"
    assert res_err["usage"] == {"total_tokens": 5}
    assert res_err["hint"] == "boot it"


def test_response_mentioning_quota_is_not_exhaustion():
    out = {"ok": False, "error": "a tool call failed", "response": "F2: quota was the cause",
           "usage": {"total_tokens": 900}}
    assert d._is_exhausted(out) is False


def test_quota_pools_opus_exhausted_skips_sonnet_same_and_next_call(routing, tmp_path, monkeypatch):
    cfg = {
        "default": "hard",
        "tiers": {
            "hard": ["claude-opus-5-5-high", "claude-sonnet-5-5-high", "gemini-3.8-flash-high"]
        },
        "quota_pools": [["claude-opus-5-5-high", "claude-sonnet-5-5-high"]]
    }
    routing.write_text(json.dumps(cfg))
    quota_file = tmp_path / "quota.json"
    monkeypatch.setattr(d, "QUOTA_PATH", quota_file)
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setattr(d, "LOG_PATH", None)
    now = 1700000000.0
    monkeypatch.setattr(time, "time", lambda: now)

    calls = []

    def fake(prompt, **kw):
        m = kw.get("model")
        calls.append(m)
        if m == "claude-opus-5-5-high":
            return {"ok": False, "error": "status ERROR", "response": "Resource exhausted. Resets in 2h"}
        return {"ok": True, "response": "done from flash"}

    out1 = d.run_agy("hi", task="hard", cwd=str(tmp_path), ask=fake)
    assert calls == ["claude-opus-5-5-high", "gemini-3.8-flash-high"]
    assert out1["ok"] is True
    assert out1["model"] == "gemini-3.8-flash-high"
    skipped_models = [s["model"] for s in out1["skipped"]]
    assert skipped_models == ["claude-opus-5-5-high", "claude-sonnet-5-5-high"]
    assert out1["skipped"][0]["reason"] == "quota exhausted"
    assert "exhausted until" in out1["skipped"][1]["reason"]

    quota = json.loads(quota_file.read_text())
    assert quota["claude-opus-5-5-high"] == now + 7200
    assert quota["claude-sonnet-5-5-high"] == now + 7200

    calls.clear()
    out2 = d.run_agy("hi second time", task="hard", cwd=str(tmp_path), ask=fake)
    assert calls == ["gemini-3.8-flash-high"]
    assert out2["ok"] is True
    assert out2["model"] == "gemini-3.8-flash-high"
    assert [s["model"] for s in out2["skipped"]] == ["claude-opus-5-5-high", "claude-sonnet-5-5-high"]
    assert all("exhausted until" in s["reason"] for s in out2["skipped"])


def test_model_in_no_pool_behaves_as_before(routing, tmp_path, monkeypatch):
    cfg = {
        "default": "hard",
        "tiers": {
            "hard": ["gemini-4-argon-high", "claude-opus-5-5-high"]
        },
        "quota_pools": [["claude-opus-5-5-high", "claude-sonnet-5-5-high"]]
    }
    routing.write_text(json.dumps(cfg))
    quota_file = tmp_path / "quota.json"
    monkeypatch.setattr(d, "QUOTA_PATH", quota_file)
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setattr(d, "LOG_PATH", None)

    calls = []

    def fake(prompt, **kw):
        m = kw.get("model")
        calls.append(m)
        if m == "gemini-4-argon-high":
            return {"ok": False, "error": "status ERROR", "response": "Resource exhausted. Resets in 1h"}
        return {"ok": True, "response": "done from opus"}

    out = d.run_agy("hi", task="hard", cwd=str(tmp_path), ask=fake)
    assert calls == ["gemini-4-argon-high", "claude-opus-5-5-high"]
    assert out["ok"] is True
    assert out["model"] == "claude-opus-5-5-high"
    quota = json.loads(quota_file.read_text())
    assert "gemini-4-argon-high" in quota
    assert "claude-opus-5-5-high" not in quota
    assert "claude-sonnet-5-5-high" not in quota


def test_missing_quota_pools_key_works(routing, tmp_path, monkeypatch):
    quota_file = tmp_path / "quota.json"
    monkeypatch.setattr(d, "QUOTA_PATH", quota_file)
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setattr(d, "LOG_PATH", None)

    r = d.load_routing()
    assert r.get("quota_pools") == []

    calls = []

    def fake(prompt, **kw):
        m = kw.get("model")
        calls.append(m)
        if m == "gemini-3.8-flash-low":
            return {"ok": False, "error": "status ERROR", "response": "Resource exhausted. Resets in 1h"}
        return {"ok": True, "response": "done"}

    out = d.run_agy("hi", task="light", cwd=str(tmp_path), ask=fake)
    assert calls == ["gemini-3.8-flash-low", "gpt-oss-120b-medium"]
    assert out["ok"] is True
    assert out["model"] == "gpt-oss-120b-medium"
    quota = json.loads(quota_file.read_text())
    assert "gemini-3.8-flash-low" in quota
    assert "gpt-oss-120b-medium" not in quota


# ── make_image extras ─────────────────────────────────────────────────────
def test_media_args_builds_flags_and_needs_absolute_ref():
    assert d.media_args() == []
    assert d.media_args(width=1344, height=768, seed=5, denoise=0.5) == [
        "--width", "1344", "--height", "768", "--seed", "5", "--denoise", "0.5"]
    assert d.media_args(ref_image="/x/a.png") == ["--ref", "/x/a.png"]
    assert "absolute" in d.media_args(ref_image="a.png")["error"]
    assert d.media_args(ref_image=["/x/a.png", "/x/b.png"], model="klein") == [
        "--model", "klein", "--ref", "/x/a.png", "--ref", "/x/b.png"]
    assert "absolute" in d.media_args(ref_image=["/x/a.png", "b.png"])["error"]


def test_run_media_passes_extras_before_prompt_and_returns_seed(monkeypatch, tmp_path):
    seen = {}

    class LC:
        OUTPUTS = tmp_path
        JOB_TIMEOUT = {"image": 9}

        @staticmethod
        def _run(cmd, timeout):
            seen["cmd"] = cmd
            return {"ok": True, "output": f"{tmp_path}/image_1.png\nimage: 50 s, seed 42"}

        @staticmethod
        def media_kind(p):
            return "image"
    monkeypatch.setattr(d, "local_chat", lambda: LC)
    monkeypatch.setattr(d, "_log", lambda *a, **k: None)
    out = d.run_media("image", "-dash prompt", extra=["--seed", "42"])
    assert out == {"ok": True, "files": [f"{tmp_path}/image_1.png"], "seed": 42}
    assert seen["cmd"][-4:] == ["--seed", "42", "--", "-dash prompt"]


# --- keep-alive: Claude Code aborts a call silent for 1800 s (mtw2, 2026-11-20) ---

class FakeCtx:
    """Stands in for FastMCP's Context: a progress token or none, and a report_progress log."""
    def __init__(self, token="tok", fail=False):
        self.calls, self.fail = [], fail
        meta = type("Meta", (), {"progressToken": token})() if token is not None else None
        self.request_context = type("RC", (), {"meta": meta})()

    async def report_progress(self, progress, total=None, message=None):
        if self.fail:
            raise RuntimeError("stream closed")
        self.calls.append((progress, message))


def test_clamp_timeout_only_without_progress():
    cap = d.CLIENT_IDLE_S - d.IDLE_MARGIN_S
    assert d.clamp_timeout(1800, pinging=True) == (1800, None)
    assert d.clamp_timeout(1800, pinging=False) == (cap, 1800)
    assert d.clamp_timeout(600, pinging=False) == (600, None)
    assert d.clamp_timeout(None, pinging=False) == (d.AGY_TIMEOUT, None)


def test_has_progress_token():
    assert d.has_progress_token(FakeCtx("t")) is True
    assert d.has_progress_token(FakeCtx(None)) is False
    assert d.has_progress_token(object()) is False


def test_keep_alive_pings_while_the_job_runs(monkeypatch):
    import asyncio
    monkeypatch.setattr(d, "PING_S", 0.05)
    ctx = FakeCtx()
    out = asyncio.run(d.keep_alive(ctx, True, lambda: (time.sleep(0.3), {"ok": True})[1]))
    assert out == {"ok": True}
    assert len(ctx.calls) >= 3 and ctx.calls[0][0] == 1


def test_keep_alive_no_token_no_pings(monkeypatch):
    import asyncio
    monkeypatch.setattr(d, "PING_S", 0.05)
    ctx = FakeCtx(None)
    assert asyncio.run(d.keep_alive(ctx, False, lambda: (time.sleep(0.2), 7)[1])) == 7
    assert ctx.calls == []


def test_keep_alive_failed_ping_keeps_the_result(monkeypatch):
    import asyncio
    monkeypatch.setattr(d, "PING_S", 0.05)
    out = asyncio.run(d.keep_alive(FakeCtx(fail=True), True, lambda: (time.sleep(0.2), "done")[1]))
    assert out == "done"


def test_keep_alive_job_error_propagates(monkeypatch):
    import asyncio
    monkeypatch.setattr(d, "PING_S", 0.05)

    def boom():
        time.sleep(0.1)
        raise ValueError("agy wrapper bug")
    with pytest.raises(ValueError):
        asyncio.run(d.keep_alive(FakeCtx(), True, boom))


def test_agy_tool_marks_clamp_and_missing_token():
    import asyncio
    seen = {}

    def run(prompt, cwd, model, timeout=None, edits=False, task=None):
        seen["timeout"] = timeout
        return {"ok": True}
    out = asyncio.run(d._agy_tool(FakeCtx(None), run, 1800, "p", "/tmp", None, edits=True, task="code"))
    assert seen["timeout"] == d.CLIENT_IDLE_S - d.IDLE_MARGIN_S
    assert out["no_progress_token"] is True
    assert out["timeout_clamped"] == {"asked": 1800, "used": seen["timeout"], "client_idle_s": d.CLIENT_IDLE_S}
    out = asyncio.run(d._agy_tool(FakeCtx("t"), run, 1800, "p", "/tmp", None))
    assert seen["timeout"] == 1800 and "timeout_clamped" not in out and "no_progress_token" not in out


def test_agy_tools_hide_ctx_from_the_schema():
    import asyncio
    tools = {t.name: t for t in asyncio.run(d.build_server().list_tools())}
    for name in ("ask_agy", "ask_agy_packet", "ask_codex"):
        props = tools[name].inputSchema["properties"]
        assert "ctx" not in props and "prompt" in props and "timeout" in props


# --- ask_codex ---------------------------------------------------------------------------------

CODEX_OK = "\n".join(json.dumps(e) for e in [
    {"type": "thread.started", "thread_id": "t-1"},
    {"type": "error", "message": "Reconnecting... 1/5 (stream disconnected)"},
    {"type": "item.completed", "item": {"id": "i0", "type": "command_execution", "command": "ls"}},
    {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": "first"}},
    {"type": "item.completed", "item": {"id": "i2", "type": "agent_message", "text": " answer "}},
    {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 3}},
]) + "\nnot json\n"


class Proc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


@pytest.fixture
def codex(tmp_path, monkeypatch):
    """A codex that exists and is logged in, jailed as a plain prefix; calls recorded."""
    monkeypatch.setattr(d, "LOCAL_ONLY_FILE", tmp_path / "none.txt")
    monkeypatch.setenv("DELEGATE_LOCAL_ONLY", "")
    monkeypatch.setattr(d, "LOG_PATH", tmp_path / "log.jsonl")
    monkeypatch.setattr(d, "QUOTA_PATH", tmp_path / "quota.json")
    monkeypatch.setattr(d, "codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(d, "codex_logged_in", lambda: True)
    monkeypatch.setattr(d.ask_agy, "jailed", lambda cmd, cwd=None: ["JAIL", cwd, *cmd])
    calls = []

    def runner(result):
        def run(cmd, **kw):
            calls.append((cmd, kw))
            if isinstance(result, BaseException):
                raise result
            return result
        return run
    return calls, runner


def test_parse_codex_events_takes_last_message_and_usage():
    ev = d.parse_codex_events(CODEX_OK)
    assert ev["messages"][-1] == "answer" and ev["thread_id"] == "t-1"
    assert ev["usage"]["output_tokens"] == 3 and ev["commands"] == 1 and not ev["errors"]


def test_codex_cmd_read_only_by_default_prompt_on_stdin():
    cmd = d.codex_cmd("/bin/codex", "/w", None, False)
    assert cmd[:2] == ["/bin/codex", "exec"] and cmd[-1] == "-"
    assert cmd[cmd.index("--sandbox") + 1] == "read-only" and "--ephemeral" in cmd and "-m" not in cmd
    cmd = d.codex_cmd("/bin/codex", "/w", "gpt-x", True)
    assert cmd[cmd.index("--sandbox") + 1] == "workspace-write" and cmd[cmd.index("-m") + 1] == "gpt-x"


def test_codex_success_runs_jailed_and_logs_no_content(tmp_path, codex):
    calls, runner = codex
    out = d.run_codex("secret prompt", cwd=str(tmp_path), run=runner(Proc(CODEX_OK)))
    assert out["ok"] and out["response"] == "answer" and out["usage"]["input_tokens"] == 10
    cmd, kw = calls[0]
    assert cmd[0] == "JAIL" and kw["input"] == "secret prompt" and "secret prompt" not in cmd
    rec = json.loads((tmp_path / "log.jsonl").read_text())
    assert rec["backend"] == "codex" and rec["ok"] and "secret" not in json.dumps(rec)


def test_codex_refuses_local_only_without_running(tmp_path, codex, monkeypatch):
    calls, runner = codex
    monkeypatch.setenv("DELEGATE_LOCAL_ONLY", str(tmp_path))
    out = d.run_codex("hi", cwd=str(tmp_path), run=runner(Proc(CODEX_OK)))
    assert out["error"] == "local_only" and not calls


def test_codex_refuses_without_jail(tmp_path, codex, monkeypatch):
    calls, runner = codex
    monkeypatch.setattr(d.ask_agy, "jailed", lambda cmd, cwd=None: None)
    out = d.run_codex("hi", cwd=str(tmp_path), run=runner(Proc(CODEX_OK)))
    assert out["error"] == "no jail" and not calls


@pytest.mark.parametrize("stdout,code", [("", 0), ('{"type": "renamed.event", "text": "x"}', 0),
                                         (CODEX_OK, 1)])
def test_codex_fails_closed_without_clean_answer(tmp_path, codex, stdout, code):
    calls, runner = codex
    out = d.run_codex("hi", cwd=str(tmp_path), run=runner(Proc(stdout, "boom", code)))
    assert out["ok"] is False and out["error"] and out["stderr"] == "boom"


def test_codex_usage_limit_marks_quota_and_skips_next(tmp_path, codex):
    calls, runner = codex
    limit = json.dumps({"type": "turn.failed", "error": {"message": "You've hit your usage limit."}})
    out = d.run_codex("hi", cwd=str(tmp_path), run=runner(Proc(limit, "", 1)))
    assert out["ok"] is False and "usage limit" in out["hint"]
    assert d.CODEX_QUOTA_KEY in d.read_quota()
    again = d.run_codex("hi", cwd=str(tmp_path), run=runner(Proc(CODEX_OK)))
    assert again["error"] == "quota exhausted" and len(calls) == 1


def test_codex_timeout_and_missing_login(tmp_path, codex, monkeypatch):
    import subprocess
    calls, runner = codex
    out = d.run_codex("hi", cwd=str(tmp_path), timeout=5,
                      run=runner(subprocess.TimeoutExpired("codex", 5)))
    assert out["ok"] is False and "timeout" in out["error"]
    monkeypatch.setattr(d, "codex_logged_in", lambda: False)
    assert d.run_codex("hi", cwd=str(tmp_path))["error"] == "not_logged_in"


def test_status_reports_codex(tmp_path, codex):
    s = d.status()["codex"]
    assert s["installed"] and s["logged_in"] and s["exhausted_until"] is None


def test_codex_tool_uses_its_own_lock(monkeypatch):
    import asyncio
    seen = {}

    async def fake_keep_alive(ctx, pinging, fn, *a, lock=None, label="agy", **kw):
        seen.update(lock=lock, label=label)
        return {"ok": True}
    monkeypatch.setattr(d, "keep_alive", fake_keep_alive)
    asyncio.run(d._agy_tool(FakeCtx(), d.run_codex, None, "hi", None, None,
                            lock=d._CODEX_LOCK, label="codex"))
    assert seen == {"lock": d._CODEX_LOCK, "label": "codex"} and d._CODEX_LOCK is not d._AGY_LOCK


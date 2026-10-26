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

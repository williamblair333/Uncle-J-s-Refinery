"""Tests for scripts/delegate/server.py. No network, agy, GPU or quota is used."""
import importlib.util
import io
import json
from pathlib import Path

REPO = Path(__file__).parent.parent


def load():
    spec = importlib.util.spec_from_file_location("delegate_server", REPO / "scripts/delegate/server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


d = load()


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
    seen = {}

    def fake(prompt, **kw):
        seen.update(kw)
        return {"ok": False, "response": "", "tool_errors": [], "denied": [], "error": "status ERROR"}

    out = d.run_agy("hi", cwd=str(tmp_path), ask=fake)
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

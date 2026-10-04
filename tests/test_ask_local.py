"""Tests for the ask_local MCP server (scripts/ask_local/server.py).

Every test drives the core functions through an httpx.MockTransport, so no
Ollama is needed. The live smoke test at the bottom runs only when a local
Ollama answers on ASK_LOCAL_URL.
"""
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts" / "ask_local"))

import server  # noqa: E402


def _chat_reply(content, prompt_tokens=40, out_tokens=12):
    return {
        "model": "qwen3.5:9b",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "total_duration": 1_500_000_000,
        "prompt_eval_count": prompt_tokens,
        "eval_count": out_tokens,
    }


def _client(handler, tmp_path):
    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ollama.test")
    return server.LocalClient(http=http, model="qwen3.5:9b", log_path=tmp_path / "ask_local.jsonl")


def _log_lines(tmp_path):
    p = tmp_path / "ask_local.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


# --- ask -------------------------------------------------------------------

def test_ask_returns_text_and_token_counts(tmp_path):
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_chat_reply("Paris"))

    out = server.ask(_client(handler, tmp_path), "Capital of France?", max_tokens=64)

    assert out["text"] == "Paris"
    assert out["model"] == "qwen3.5:9b"
    assert out["tokens_in"] == 40 and out["tokens_out"] == 12
    assert seen["path"] == "/api/chat"
    body = seen["body"]
    assert body["stream"] is False
    assert body["think"] is False
    assert body["options"]["num_predict"] == 64
    assert body["messages"][-1] == {"role": "user", "content": "Capital of France?"}


def test_ask_passes_system_prompt_first(tmp_path):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_chat_reply("ok"))

    server.ask(_client(handler, tmp_path), "hi", system="Be terse.")
    assert seen["body"]["messages"][0] == {"role": "system", "content": "Be terse."}


def test_unreachable_ollama_is_a_structured_error(tmp_path):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    out = server.ask(_client(handler, tmp_path), "hi")
    assert out["error"] == "ollama_unreachable"
    assert "text" not in out


def test_missing_model_is_a_structured_error(tmp_path):
    def handler(request):
        return httpx.Response(404, json={"error": "model 'nope' not found"})

    out = server.ask(_client(handler, tmp_path), "hi", model="nope")
    assert out["error"] == "model_not_found"
    assert "nope" in out["detail"]


def test_timeout_is_a_structured_error(tmp_path):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    out = server.ask(_client(handler, tmp_path), "hi")
    assert out["error"] == "timeout"


# --- summarize -------------------------------------------------------------

def test_summarize_reads_file_server_side(tmp_path):
    doc = tmp_path / "notes.md"
    doc.write_text("The deploy failed because the disk was full.")
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_chat_reply("Disk full broke the deploy."))

    out = server.summarize(_client(handler, tmp_path), path=str(doc), focus="root cause")

    assert out["text"] == "Disk full broke the deploy."
    prompt = seen["body"]["messages"][-1]["content"]
    assert "disk was full" in prompt
    assert "root cause" in prompt
    assert out["input_chars"] == len(doc.read_text())


def test_summarize_requires_exactly_one_source(tmp_path):
    c = _client(lambda r: httpx.Response(200, json=_chat_reply("x")), tmp_path)
    assert server.summarize(c)["error"] == "bad_arguments"
    assert server.summarize(c, path="/x", text="y")["error"] == "bad_arguments"


def test_summarize_rejects_missing_file(tmp_path):
    c = _client(lambda r: httpx.Response(200, json=_chat_reply("x")), tmp_path)
    assert server.summarize(c, path=str(tmp_path / "nope.txt"))["error"] == "file_not_found"


def test_summarize_rejects_oversize_file(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "MAX_INPUT_BYTES", 10)
    big = tmp_path / "big.txt"
    big.write_text("x" * 11)
    c = _client(lambda r: httpx.Response(200, json=_chat_reply("x")), tmp_path)
    assert server.summarize(c, path=str(big))["error"] == "input_too_large"


def test_summarize_rejects_binary_file(tmp_path):
    blob = tmp_path / "img.bin"
    blob.write_bytes(b"\x89PNG\x00\x00\x01")
    c = _client(lambda r: httpx.Response(200, json=_chat_reply("x")), tmp_path)
    assert server.summarize(c, path=str(blob))["error"] == "binary_file"


@pytest.mark.parametrize("rel", [
    ".ssh/id_ed25519", ".gnupg/secring.gpg", ".claude.json", ".aws/credentials",
    "proj/app/.env", "proj/app/.env.production", "proj/app/secrets.toml",
    "proj/app/server.pem", "proj/app/tls.key", ".config/gh/hosts.yml", ".netrc",
])
def test_secret_paths_are_refused(tmp_path, rel):
    secret = tmp_path / rel
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("TOKEN=hunter2")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_chat_reply("x"))

    out = server.summarize(_client(handler, tmp_path), path=str(secret))
    assert out["error"] == "path_refused"
    assert calls == []  # never reached the model


def test_symlink_to_secret_is_refused(tmp_path):
    secret = tmp_path / ".ssh" / "id_rsa"
    secret.parent.mkdir()
    secret.write_text("KEY")
    link = tmp_path / "innocent.txt"
    link.symlink_to(secret)
    c = _client(lambda r: httpx.Response(200, json=_chat_reply("x")), tmp_path)
    assert server.summarize(c, path=str(link))["error"] == "path_refused"


@pytest.mark.parametrize("name", ["environment.md", "collect_token_cost.py", "keys.md"])
def test_ordinary_names_are_allowed(tmp_path, name):
    ok = tmp_path / name
    ok.write_text("notes")
    c = _client(lambda r: httpx.Response(200, json=_chat_reply("fine")), tmp_path)
    assert server.summarize(c, path=str(ok))["text"] == "fine"


# --- extract ---------------------------------------------------------------

SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
    "required": ["name", "age"],
}


def test_extract_constrains_output_to_schema(tmp_path):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_chat_reply('{"name": "Ada", "age": 36}'))

    out = server.extract(_client(handler, tmp_path), "Get the person.", SCHEMA,
                         text="Ada Lovelace was 36.")
    assert out["data"] == {"name": "Ada", "age": 36}
    assert seen["body"]["format"] == SCHEMA
    assert seen["body"]["options"]["temperature"] == 0


def test_extract_reports_unparseable_output(tmp_path):
    c = _client(lambda r: httpx.Response(200, json=_chat_reply("not json")), tmp_path)
    out = server.extract(c, "Get the person.", SCHEMA, text="Ada")
    assert out["error"] == "invalid_json"
    assert out["raw"] == "not json"


def test_extract_reports_missing_required_keys(tmp_path):
    c = _client(lambda r: httpx.Response(200, json=_chat_reply('{"name": "Ada"}')), tmp_path)
    out = server.extract(c, "Get the person.", SCHEMA, text="Ada")
    assert out["error"] == "schema_mismatch"
    assert out["missing"] == ["age"]


# --- status ----------------------------------------------------------------

def test_status_lists_installed_models(tmp_path):
    def handler(request):
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.35.1"})
        return httpx.Response(200, json={"models": [
            {"name": "qwen3.5:9b", "size": 6_600_000_000},
            {"name": "granite4.2:8b", "size": 5_300_000_000},
        ]})

    out = server.status(_client(handler, tmp_path))
    assert out["version"] == "0.35.1"
    assert out["default_model"] == "qwen3.5:9b"
    assert [m["name"] for m in out["models"]] == ["qwen3.5:9b", "granite4.2:8b"]
    assert out["models"][0]["size_gb"] == 6.6


# --- measurement log -------------------------------------------------------

def test_every_call_is_logged_without_content(tmp_path):
    def handler(request):
        return httpx.Response(200, json=_chat_reply("secret answer"))

    server.ask(_client(handler, tmp_path), "secret question")
    lines = _log_lines(tmp_path)
    assert len(lines) == 1
    rec = lines[0]
    assert rec["tool"] == "ask" and rec["ok"] is True
    assert rec["tokens_in"] == 40 and rec["tokens_out"] == 12
    assert "seconds" in rec and "ts" in rec
    assert "secret" not in json.dumps(rec)


def test_failed_calls_are_logged_too(tmp_path):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    server.ask(_client(handler, tmp_path), "hi")
    rec = _log_lines(tmp_path)[0]
    assert rec["ok"] is False and rec["error"] == "ollama_unreachable"


def test_results_strip_null_fields(tmp_path):
    reply = _chat_reply("x")
    del reply["prompt_eval_count"]  # Ollama omits it on a cached prompt
    c = _client(lambda r: httpx.Response(200, json=reply), tmp_path)
    out = server.ask(c, "hi")
    assert "tokens_in" not in out


# --- live smoke test -------------------------------------------------------

def _ollama_up():
    try:
        httpx.get(server.OLLAMA_URL + "/api/version", timeout=1.0)
        return True
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not _ollama_up(), reason="no local Ollama")
def test_live_status_round_trip():
    c = server.LocalClient(http=httpx.Client(base_url=server.OLLAMA_URL, timeout=5.0),
                           model=server.DEFAULT_MODEL, log_path=None)
    out = server.status(c)
    assert "error" not in out
    assert "version" in out

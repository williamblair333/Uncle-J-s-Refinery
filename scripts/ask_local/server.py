"""ask_local — MCP server that hands bounded subtasks to a local Ollama model.

Claude stays the orchestrator. This server only answers prompts, summarizes
and extracts; it has no shell, writes no files, and reads a file only when a
tool is given its path (so a large input never enters Claude's context).

Every call appends one line to the measurement log (tool, model, token counts,
latency, ok/error) and never the prompt or the answer, so whether offloading
pays for itself can be measured rather than assumed.

Env: ASK_LOCAL_URL (default http://127.0.0.1:11434), ASK_LOCAL_MODEL
(default qwen3.5:9b), ASK_LOCAL_TIMEOUT seconds (default 300),
ASK_LOCAL_LOG (default <repo>/state/ask_local.jsonl; empty string disables).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

_REPO = Path(__file__).resolve().parents[2]

OLLAMA_URL = os.environ.get("ASK_LOCAL_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("ASK_LOCAL_MODEL", "qwen3.5:9b")
TIMEOUT_S = float(os.environ.get("ASK_LOCAL_TIMEOUT", "300"))
_log_env = os.environ.get("ASK_LOCAL_LOG")
LOG_PATH = None if _log_env == "" else Path(_log_env or _REPO / "state" / "ask_local.jsonl")
MAX_INPUT_BYTES = 256_000  # ~64k tokens; above that a 16k-context model truncates


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None and v != [] and v != {}}


class LocalClient:
    """Ollama HTTP client plus the measurement log. `http` is injectable for tests."""

    def __init__(self, http: httpx.Client, model: str = DEFAULT_MODEL,
                 log_path: Path | None = LOG_PATH):
        self.http = http
        self.model = model
        self.log_path = log_path

    def _log(self, rec: dict) -> None:
        if self.log_path is None:
            return
        rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **rec}
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a") as f:
                f.write(json.dumps(_clean(rec), separators=(",", ":")) + "\n")
        except OSError:
            pass  # measurement must never break the tool

    def chat(self, tool: str, prompt: str, *, system: str | None = None,
             model: str | None = None, max_tokens: int = 1024,
             fmt: dict | None = None, temperature: float | None = None,
             input_chars: int | None = None) -> dict:
        model = model or self.model
        messages = ([{"role": "system", "content": system}] if system else [])
        messages.append({"role": "user", "content": prompt})
        options = {"num_predict": max_tokens}
        if temperature is not None:
            options["temperature"] = temperature
        body = {"model": model, "messages": messages, "stream": False,
                "think": False, "options": options}
        if fmt is not None:
            body["format"] = fmt

        start = time.monotonic()
        result = self._post_chat(body, model)
        seconds = round(time.monotonic() - start, 2)
        result.update(seconds=seconds, input_chars=input_chars)
        self._log({"tool": tool, "model": model, "ok": "error" not in result,
                   "error": result.get("error"), "tokens_in": result.get("tokens_in"),
                   "tokens_out": result.get("tokens_out"), "input_chars": input_chars,
                   "seconds": seconds})
        return _clean(result)

    def _post_chat(self, body: dict, model: str) -> dict:
        try:
            r = self.http.post("/api/chat", json=body, timeout=TIMEOUT_S)
        except httpx.TimeoutException as e:
            return {"error": "timeout", "detail": f"no reply within {TIMEOUT_S:.0f}s ({e})"}
        except httpx.HTTPError as e:
            return {"error": "ollama_unreachable", "detail": f"{OLLAMA_URL}: {e}"}
        if r.status_code == 404:
            return {"error": "model_not_found", "detail": _err_text(r) or model}
        if r.status_code >= 400:
            return {"error": "ollama_error", "detail": f"HTTP {r.status_code}: {_err_text(r)}"}
        data = r.json()
        return {"model": data.get("model", model),
                "text": (data.get("message") or {}).get("content", ""),
                "tokens_in": data.get("prompt_eval_count"),
                "tokens_out": data.get("eval_count")}


def _err_text(r: httpx.Response) -> str:
    try:
        return str(r.json().get("error", ""))
    except ValueError:
        return r.text[:200]


# This server reads files outside Claude Code's permission rules, so it refuses
# credential stores itself. Checked against the symlink-resolved path.
_SECRET_DIRS = {".ssh", ".gnupg", ".aws", ".kube", ".docker", ".password-store"}
_SECRET_NAMES = {".claude.json", ".netrc", ".pgpass", "credentials", "hosts.yml",
                 "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"}
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")
_SECRET_STEMS = ("secret", "credential")  # not "token": collect_token_cost.py is code


def _is_secret_path(p: Path) -> bool:
    parts = set(p.parts)
    name = p.name.lower()
    return bool(
        parts & _SECRET_DIRS
        or name in _SECRET_NAMES
        or name == ".env" or name.startswith(".env.")
        or name.endswith(_SECRET_SUFFIXES)
        or any(s in name for s in _SECRET_STEMS)
    )


def _read_input(path: str | None, text: str | None) -> tuple[str | None, dict | None]:
    if (path is None) == (text is None):
        return None, {"error": "bad_arguments", "detail": "pass exactly one of path or text"}
    if text is not None:
        if len(text.encode()) > MAX_INPUT_BYTES:
            return None, {"error": "input_too_large", "detail": f"limit {MAX_INPUT_BYTES} bytes"}
        return text, None
    p = Path(path).expanduser().resolve()
    if _is_secret_path(p):
        return None, {"error": "path_refused", "detail": "credential-like path"}
    if not p.is_file():
        return None, {"error": "file_not_found", "detail": str(p)}
    if p.stat().st_size > MAX_INPUT_BYTES:
        return None, {"error": "input_too_large",
                      "detail": f"{p.stat().st_size} bytes > limit {MAX_INPUT_BYTES}"}
    raw = p.read_bytes()
    if b"\x00" in raw[:8192]:
        return None, {"error": "binary_file", "detail": str(p)}
    return raw.decode("utf-8", errors="replace"), None


# --- tool bodies (plain functions so tests can call them directly) ----------

def ask(client: LocalClient, prompt: str, system: str | None = None,
        model: str | None = None, max_tokens: int = 1024) -> dict:
    return client.chat("ask", prompt, system=system, model=model, max_tokens=max_tokens,
                       input_chars=len(prompt))


def summarize(client: LocalClient, path: str | None = None, text: str | None = None,
              focus: str | None = None, max_words: int = 200,
              model: str | None = None) -> dict:
    content, err = _read_input(path, text)
    if err:
        return err
    ask_for = f"Summarize the document below in at most {max_words} words."
    if focus:
        ask_for += f" Focus on: {focus}."
    ask_for += " Report only what the document says; do not add facts."
    prompt = f"{ask_for}\n\n<document>\n{content}\n</document>"
    return client.chat("summarize", prompt, model=model, max_tokens=max(256, max_words * 3),
                       temperature=0.2, input_chars=len(content))


def extract(client: LocalClient, instruction: str, schema: dict, path: str | None = None,
            text: str | None = None, model: str | None = None) -> dict:
    content, err = _read_input(path, text)
    if err:
        return err
    prompt = (f"{instruction}\nAnswer with JSON matching the given schema, using only "
              f"information in the document.\n\n<document>\n{content}\n</document>")
    out = client.chat("extract", prompt, model=model, max_tokens=2048, fmt=schema,
                      temperature=0, input_chars=len(content))
    if "error" in out:
        return out
    raw = out.pop("text", "")
    try:
        data = json.loads(raw)
    except ValueError:
        return _clean({**out, "error": "invalid_json", "raw": raw[:2000]})
    missing = [k for k in schema.get("required", []) if not (isinstance(data, dict) and k in data)]
    if missing:
        return _clean({**out, "error": "schema_mismatch", "missing": missing, "data": data})
    return {**out, "data": data}


def status(client: LocalClient) -> dict:
    try:
        version = client.http.get("/api/version", timeout=5).json().get("version")
        tags = client.http.get("/api/tags", timeout=5).json().get("models", [])
    except httpx.HTTPError as e:
        return {"error": "ollama_unreachable", "detail": f"{OLLAMA_URL}: {e}"}
    models = [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 1)} for m in tags]
    return _clean({"version": version, "url": OLLAMA_URL, "default_model": client.model,
                   "models": models})


# --- MCP wiring -------------------------------------------------------------

def build_server():
    import logging

    from mcp.server.fastmcp import FastMCP

    logging.getLogger("httpx").setLevel(logging.WARNING)
    client = LocalClient(http=httpx.Client(base_url=OLLAMA_URL))
    mcp = FastMCP("ask_local", log_level="WARNING", instructions=(
        "Hand bounded, low-stakes subtasks to a local model on this machine: bulk "
        "summarizing, first drafts, classification, structured extraction. Results are "
        "from a ~9B model — verify anything that matters. Prefer path= over pasting "
        "large text, so the content stays out of your context."))

    @mcp.tool(name="local_status")
    def _status() -> dict:
        """Is the local Ollama up, and which models are installed."""
        return status(client)

    @mcp.tool(name="ask_local")
    def _ask(prompt: str, system: str | None = None, model: str | None = None,
             max_tokens: int = 1024) -> dict:
        """Send one prompt to the local model and return its answer with token counts."""
        return ask(client, prompt, system, model, max_tokens)

    @mcp.tool(name="summarize_local")
    def _summarize(path: str | None = None, text: str | None = None,
                   focus: str | None = None, max_words: int = 200,
                   model: str | None = None) -> dict:
        """Summarize a text file (read server-side, ≤256 KB) or a text block. Pass exactly one of path/text."""
        return summarize(client, path, text, focus, max_words, model)

    @mcp.tool(name="extract_local")
    def _extract(instruction: str, schema: dict, path: str | None = None,
                 text: str | None = None, model: str | None = None) -> dict:
        """Extract JSON matching a JSON Schema from a file or text block. Output is schema-constrained and checked for required keys."""
        return extract(client, instruction, schema, path, text, model)

    return mcp


if __name__ == "__main__":
    build_server().run()

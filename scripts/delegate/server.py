#!/usr/bin/env python3
"""delegate MCP server: hand work to a model other than Claude, from any project.

Usage:
  server.py            # stdio MCP server (registered at user scope by install.sh)

Backends, one tool each:

- ask_agy:     Antigravity CLI (Gemini Flash by default) via scripts/ask_agy.py, which fails
               honestly when agy claims success it didn't have. Google AI Pro quota.
- ask_heretic: the local llama-server (Heretic) on :8090. Nothing leaves the machine.
- ask_openai:  any OpenAI-compatible API. Off until the env var named by
               DELEGATE_OPENAI_KEY_ENV (default OPENAI_API_KEY) holds a key and
               DELEGATE_OPENAI_MODEL names a model; DELEGATE_OPENAI_URL picks the endpoint.
- make_image / make_video / speak: ComfyUI and Chatterbox, through scripts/local_chat.

Off-machine backends (agy, openai) refuse when the working directory, or any path named in
the prompt, is under a root listed in config/delegate-local-only.txt or DELEGATE_LOCAL_ONLY
(os.pathsep separated). Claude Code starts stdio servers in the session's project
directory, so a session inside a local-only repo can't ship it to Google or OpenAI.

Every call is logged to state/delegate.jsonl (backend, model, seconds, ok; no content).
"""
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts"))
import ask_agy  # noqa: E402

AGY_MODEL = os.environ.get("DELEGATE_AGY_MODEL", "gemini-3.8-flash-medium")
AGY_TIMEOUT = int(os.environ.get("DELEGATE_AGY_TIMEOUT", "300"))
OPENAI_URL = os.environ.get("DELEGATE_OPENAI_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.environ.get("DELEGATE_OPENAI_MODEL", "")
OPENAI_KEY_ENV = os.environ.get("DELEGATE_OPENAI_KEY_ENV", "OPENAI_API_KEY")
LOCAL_ONLY_FILE = _REPO / "config" / "delegate-local-only.txt"
_log_env = os.environ.get("DELEGATE_LOG")
LOG_PATH = None if _log_env == "" else Path(_log_env or _REPO / "state" / "delegate.jsonl")
_PATHLIKE = re.compile(r"(?:~|/)[^\s'\"`<>|;,)]+")
_local_chat = None


def local_chat():
    """scripts/local_chat/server.py, loaded on first use so a break there can't stop agy."""
    global _local_chat
    if _local_chat is None:
        spec = importlib.util.spec_from_file_location(
            "local_chat_server", _REPO / "scripts" / "local_chat" / "server.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _local_chat = mod
    return _local_chat


def local_only_roots(path: Path = LOCAL_ONLY_FILE, env: str | None = None) -> list[Path]:
    """Directories whose contents must not reach an off-machine model."""
    lines = path.read_text().splitlines() if path.is_file() else []
    extra = (os.environ.get("DELEGATE_LOCAL_ONLY", "") if env is None else env).split(os.pathsep)
    roots = []
    for raw in lines + extra:
        raw = raw.split("#", 1)[0].strip()
        if raw:
            roots.append(Path(os.path.expanduser(raw)).resolve())
    return roots


def _under(p: Path, roots: list[Path]) -> str | None:
    for root in roots:
        if p == root or root in p.parents:
            return str(root)
    return None


def local_only_block(cwd: str, prompt: str = "", roots: list[Path] | None = None) -> str | None:
    """The local-only root that cwd or a path in the prompt falls under, else None."""
    roots = local_only_roots() if roots is None else roots
    if hit := _under(Path(cwd).resolve(), roots):
        return hit
    for m in _PATHLIKE.findall(prompt):
        m = m.rstrip(".?!:")
        try:
            p = Path(os.path.expanduser(m)).resolve()
        except (OSError, RuntimeError):
            continue
        if hit := _under(p, roots):
            return hit
    return None


def _log(backend: str, model: str | None, started: float, out: dict) -> None:
    if LOG_PATH is None:
        return
    rec = {"ts": round(time.time(), 1), "backend": backend, "model": model,
           "seconds": round(time.time() - started, 1), "ok": bool(out.get("ok"))}
    if not out.get("ok"):
        rec["error"] = str(out.get("error", ""))[:200]
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def _refused(cwd: str, prompt: str) -> dict | None:
    root = local_only_block(cwd, prompt)
    if root:
        return {"ok": False, "error": "local_only",
                "detail": f"{root} is local-only; use ask_heretic or do it yourself"}
    return None


def run_agy(prompt: str, cwd: str | None = None, model: str | None = None,
            timeout: int | None = None, edits: bool = False, ask=ask_agy.ask) -> dict:
    cwd = cwd or os.getcwd()
    if refused := _refused(cwd, prompt):
        return refused
    model = model or AGY_MODEL
    started = time.time()
    out = ask(prompt, cwd=cwd, edits=edits, timeout=timeout or AGY_TIMEOUT, model=model)
    out = {k: v for k, v in out.items() if v is not None and v != [] and v != {} and v != ""}
    out["ok"] = bool(out.get("ok"))
    out["model"] = model
    if out.get("error") == "status ERROR":
        out["hint"] = ("zero-token ERROR is usually an expired login or exhausted AI Pro quota; "
                       "run `agy` in a terminal, else fall back to ask_heretic or do it yourself")
    _log("agy", model, started, out)
    return out


def run_openai(prompt: str, system: str | None = None, model: str | None = None,
               max_tokens: int = 2048, cwd: str | None = None, opener=urllib.request.urlopen) -> dict:
    key = os.environ.get(OPENAI_KEY_ENV)
    model = model or OPENAI_MODEL
    if not key or not model:
        return {"ok": False, "error": "not_configured",
                "detail": f"set {OPENAI_KEY_ENV} and DELEGATE_OPENAI_MODEL in the server's env"}
    if refused := _refused(cwd or os.getcwd(), f"{system or ''}\n{prompt}"):
        return refused
    messages = ([{"role": "system", "content": system}] if system else []) + \
        [{"role": "user", "content": prompt}]
    body = json.dumps({"model": model, "messages": messages, "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(f"{OPENAI_URL}/chat/completions", body,
                                 {"Content-Type": "application/json",
                                  "Authorization": f"Bearer {key}"})
    started = time.time()
    try:
        with opener(req, timeout=600) as resp:
            data = json.load(resp)
        text = (data["choices"][0]["message"].get("content") or "").strip()
        out = {"ok": bool(text), "text": text, "usage": data.get("usage"), "model": model}
        if not text:
            out["error"] = "empty answer"
    except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError) as e:
        out = {"ok": False, "error": f"openai-compatible call failed: {e}", "model": model}
    _log("openai", model, started, out)
    return out


def run_heretic(prompt: str, system: str | None = None, think: bool = False) -> dict:
    messages = ([{"role": "system", "content": system}] if system else []) + \
        [{"role": "user", "content": prompt}]
    started = time.time()
    out = local_chat().ask_heretic(messages, think=think)
    if not out["ok"] and "unreachable" in out.get("error", ""):
        out["hint"] = "start it from the chat page (:8091) or scripts/heretic.sh"
    _log("heretic", "heretic", started, out)
    return out


def run_media(kind: str, prompt: str) -> dict:
    lc = local_chat()
    started = time.time()
    if kind == "speak":
        out = lc.speak(prompt)
    else:
        r = lc._run([sys.executable, str(_REPO / "scripts" / "comfy_job.py"), kind, prompt],
                    timeout=lc.JOB_TIMEOUT[kind])
        files = [p for p in r["output"].splitlines()
                 if p.startswith(str(lc.OUTPUTS)) and lc.media_kind(p)]
        out = {"ok": r["ok"] and bool(files), "files": files}
        if not out["ok"]:
            out["error"] = r["output"][-1500:]
    _log(kind, None, started, out)
    return out


def status() -> dict:
    try:
        with urllib.request.urlopen(f"{local_chat().LLAMA_URL}/v1/models", timeout=3):
            heretic = "up"
    except Exception:  # noqa: BLE001 — unreachable or local_chat failed to load: both mean down
        heretic = "down"
    cwd = os.getcwd()
    return {
        "agy": {"installed": bool(shutil.which(os.environ.get("AGY_BIN") or "agy")),
                "model": AGY_MODEL},
        "heretic": heretic,
        "openai": "configured" if os.environ.get(OPENAI_KEY_ENV) and OPENAI_MODEL else "not_configured",
        "cwd": cwd,
        "local_only": local_only_block(cwd),
    }


def build_server():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("delegate", log_level="WARNING", instructions=(
        "Hand work to a model other than Claude: Gemini via agy (subscription quota, off "
        "machine), Heretic (local, private, uncensored), an OpenAI-compatible API when "
        "configured, and local image/video/speech. Decide the check before delegating and run "
        "it on what comes back (verifiable-task skill); a helper's own 'done' is not evidence. "
        "agy/openai refuse inside local-only repos."))

    @mcp.tool(name="delegate_status")
    def _status() -> dict:
        """Which delegate backends are usable here, and whether this directory is local-only."""
        return status()

    @mcp.tool(name="ask_agy")
    def _agy(prompt: str, cwd: str | None = None, model: str | None = None,
             timeout: int | None = None, edits: bool = False) -> dict:
        """Run one prompt in Antigravity CLI (default Gemini Flash). agy can read files and call
        the stack's MCP servers under a read-only allow list; edits=True lets it write inside
        cwd. Default cwd is this session's project. Takes seconds to minutes."""
        return run_agy(prompt, cwd, model, timeout, edits)

    @mcp.tool(name="ask_heretic")
    def _heretic(prompt: str, system: str | None = None, think: bool = False) -> dict:
        """Ask the local Heretic model. Nothing leaves this machine; use for private or
        local-only material. think=True is much slower."""
        return run_heretic(prompt, system, think)

    @mcp.tool(name="ask_openai")
    def _openai(prompt: str, system: str | None = None, model: str | None = None,
                max_tokens: int = 2048) -> dict:
        """Ask an OpenAI-compatible API. Returns error not_configured until a key is set."""
        return run_openai(prompt, system, model, max_tokens)

    @mcp.tool(name="make_image")
    def _image(prompt: str) -> dict:
        """Text-to-image (Z-Image-Turbo on ComfyUI, ~1 min). Returns saved file paths."""
        return run_media("image", prompt)

    @mcp.tool(name="make_video")
    def _video(prompt: str) -> dict:
        """Text-to-video (Wan 2.2, ~8 min for 5 s). Returns saved file paths."""
        return run_media("video", prompt)

    @mcp.tool(name="speak")
    def _speak(text: str) -> dict:
        """Text-to-speech (Chatterbox). Returns media.path, the saved wav."""
        return run_media("speak", text)

    return mcp


if __name__ == "__main__":
    build_server().run()

#!/usr/bin/env python3
"""delegate MCP server: hand work to a model other than Claude, from any project.

Usage:
  server.py            # stdio MCP server (registered at user scope by install.sh)

Backends, one tool each:

- ask_agy:     Antigravity CLI via scripts/ask_agy.py, which fails honestly when agy claims
               success it didn't have. Google AI Pro quota. `task` picks a tier from
               config/delegate-routing.json (an ordered model list); a model whose quota is
               spent is recorded in state/agy-quota.json until its reset time and skipped,
               and the next model in the tier answers. `model` bypasses the tiers. A tier
               entry named "local:heretic" or "local:ask_local" is a free local model
               (Heretic, the ask_local Ollama model) tried in order; it is skipped for
               edits=True or a prompt naming a path, since it cannot read files or run tools.
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
import datetime
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
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
ROUTING_FILE = _REPO / "config" / "delegate-routing.json"
QUOTA_PATH = Path(os.environ.get("DELEGATE_QUOTA_FILE") or _REPO / "state" / "agy-quota.json")
DEFAULT_QUOTA_SECONDS = 3600
_RESET_RE = re.compile(r"resets?\s+in\s+(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?", re.I)
_log_env = os.environ.get("DELEGATE_LOG")
LOG_PATH = None if _log_env == "" else Path(_log_env or _REPO / "state" / "delegate.jsonl")
_PATHLIKE = re.compile(r"(?:~|/)[^\s'\"`<>|;,)]+")
LOCAL_PREFIX = "local:"
_local_chat = None
_ask_local = None


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


def ask_local_mod():
    """scripts/ask_local/server.py, loaded on first use like local_chat()."""
    global _ask_local
    if _ask_local is None:
        spec = importlib.util.spec_from_file_location(
            "ask_local_server", _REPO / "scripts" / "ask_local" / "server.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ask_local = mod
    return _ask_local


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
    if out.get("tools"):
        rec["tools"] = out["tools"]
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


def load_routing(path: Path | None = None) -> dict:
    """{"default": tier, "tiers": {tier: [model, ...]}} from config/delegate-routing.json.

    A missing or malformed file falls back to one "code" tier holding AGY_MODEL."""
    try:
        data = json.loads((path or ROUTING_FILE).read_text())
        tiers = {t: [m for m in ms if isinstance(m, str) and m]
                 for t, ms in data["tiers"].items() if isinstance(ms, list)}
        tiers = {t: ms for t, ms in tiers.items() if ms}
        if tiers:
            default = data.get("default")
            return {"default": default if default in tiers else next(iter(tiers)), "tiers": tiers}
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        pass
    return {"default": "code", "tiers": {"code": [AGY_MODEL]}}


def read_quota(now: float | None = None) -> dict[str, float]:
    """{model: unix_until} for models still exhausted. Missing or corrupt file = {}."""
    now = time.time() if now is None else now
    try:
        data = json.loads(QUOTA_PATH.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {m: float(u) for m, u in data.items()
            if isinstance(m, str) and isinstance(u, (int, float)) and not isinstance(u, bool)
            and u > now}


def reset_seconds(text: str) -> int:
    """Seconds from a "Resets in 97h54m55s" message; DEFAULT_QUOTA_SECONDS if absent."""
    m = _RESET_RE.search(text or "")
    if m and any(m.groups()):
        h, mi, s = (int(g or 0) for g in m.groups())
        if total := h * 3600 + mi * 60 + s:
            return total
    return DEFAULT_QUOTA_SECONDS


def mark_exhausted(model: str, text: str = "", now: float | None = None) -> float:
    """Record model as exhausted until the reset time in text; atomic write. Returns until."""
    now = time.time() if now is None else now
    until = now + reset_seconds(text)
    quota = read_quota(now)
    quota[model] = until
    tmp = None
    try:
        QUOTA_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=QUOTA_PATH.parent, prefix=".agy-quota.")
        with os.fdopen(fd, "w") as f:
            json.dump(quota, f)
        os.replace(tmp, QUOTA_PATH)
        tmp = None
    except OSError:
        pass
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return until


def _is_exhausted(out: dict) -> bool:
    """A failed agy result that means the model's quota is spent, not that the task failed."""
    if out.get("ok"):
        return False
    # agy's own error text only: a response that merely discusses quota is not exhaustion
    text = f"{out.get('error', '')} {out.get('detail', '')}".lower()
    if "resource_exhausted" in text or "individual quota reached" in text:
        return True
    usage = out.get("usage")
    tokens = (usage.get("total_tokens") or usage.get("totalTokens") or 0) if isinstance(usage, dict) else 0
    if out.get("error") == "status ERROR" and not tokens:
        return True
    return False


def _copy_agy_log(model: str, started: float, conversation_id: str | None = None) -> str | None:
    """Copy the agy run's CLI log on failure to state/agy-logs, keeping newest 50.

    Prefers a candidate whose contents contain conversation_id; falls back to newest."""
    try:
        src_env = os.environ.get("DELEGATE_AGY_LOG_SRC")
        src_dir = Path(src_env).expanduser() if src_env else (Path.home() / ".gemini" / "antigravity-cli" / "log")
        if not src_dir.is_dir():
            return None
        candidates = []
        for p in src_dir.glob("cli-*.log"):
            try:
                st = p.stat()
                if st.st_mtime >= (started - 0.01):
                    candidates.append((st.st_mtime, p))
            except OSError:
                continue
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])

        chosen = None
        if conversation_id:
            for _, p in reversed(candidates):
                try:
                    if conversation_id in p.read_text(errors="ignore"):
                        chosen = p
                        break
                except OSError:
                    continue
        if chosen is None:
            chosen = candidates[-1][1]

        dest_env = os.environ.get("DELEGATE_AGY_LOG_DIR")
        dest_dir = Path(dest_env).expanduser() if dest_env else (_REPO / "state" / "agy-logs")
        dest_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_model = model.replace("/", "_")
        dest = dest_dir / f"{stamp}-{safe_model}.log"
        counter = 1
        while dest.exists():
            dest = dest_dir / f"{stamp}-{safe_model}-{counter}.log"
            counter += 1

        shutil.copy2(chosen, dest)

        # prune to newest 50
        all_logs = []
        for p in dest_dir.glob("*.log"):
            try:
                all_logs.append((p.stat().st_mtime, p))
            except OSError:
                continue
        all_logs.sort(key=lambda x: x[0])
        if len(all_logs) > 50:
            for _, old_path in all_logs[:-50]:
                try:
                    old_path.unlink()
                except OSError:
                    pass
        return str(dest)
    except Exception:
        return None


def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat(timespec="seconds")


_STATUS_ERROR_HINT = ("zero-token ERROR is usually an expired login or exhausted AI Pro quota; "
                      "run `agy` in a terminal, else fall back to ask_heretic or do it yourself")
_LOCAL_CANNOT = "local model cannot read files or edit"


def _heretic_raw(prompt: str, system: str | None = None, think: bool = False) -> dict:
    """One Heretic call, unlogged: {"ok", "text", "usage"} or {"ok": False, "error"}."""
    messages = ([{"role": "system", "content": system}] if system else []) + \
        [{"role": "user", "content": prompt}]
    out = local_chat().ask_heretic(messages, think=think)
    if not out["ok"] and "unreachable" in out.get("error", ""):
        out["hint"] = "start it from the chat page (:8091) or scripts/heretic.sh"
    return out


def run_ask_local(prompt: str) -> dict:
    """One prompt to the ask_local model (Ollama by default): {"text", ...} or {"error", ...}."""
    al = ask_local_mod()
    with al.httpx.Client(base_url=al.OLLAMA_URL, timeout=al.TIMEOUT_S) as http:
        return al.ask(al.LocalClient(http), prompt)


def _local_result(name: str, raw) -> dict:
    """A local backend's result in agy's shape: {"ok", "response", "model"} plus "error"."""
    raw = raw if isinstance(raw, dict) else {}
    text = next((raw[k] for k in ("text", "response", "answer") if isinstance(raw.get(k), str)), "")
    text = text.strip()
    backend_ok = bool(raw.get("ok", "error" not in raw))
    if backend_ok and text:
        res = {"ok": True, "response": text, "model": name}
        if raw.get("usage"):
            res["usage"] = raw["usage"]
        if raw.get("hint"):
            res["hint"] = raw["hint"]
        return res
    if backend_ok:
        err = "empty response"
    else:
        err = str(raw.get("error") or "failed")
        if raw.get("detail"):
            err = f"{err}: {raw['detail']}"
    err_res = {"ok": False, "error": err, "model": name}
    if raw.get("usage"):
        err_res["usage"] = raw["usage"]
    if raw.get("hint"):
        err_res["hint"] = raw["hint"]
    return err_res


def _call_local(name: str, prompt: str, local: dict) -> dict:
    fn = local.get(name)
    if fn is None:
        return {"ok": False, "error": f"unknown local backend {name!r}", "model": name}
    started = time.time()
    try:
        raw = fn(prompt)
    except Exception as e:  # noqa: BLE001 — a broken local backend must fall through, not crash
        raw = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    out = _local_result(name, raw)
    _log("local", name, started, out)
    return out


def run_agy(prompt: str, cwd: str | None = None, model: str | None = None,
            timeout: int | None = None, edits: bool = False, ask=ask_agy.ask,
            task: str | None = None, local: dict | None = None) -> dict:
    cwd = cwd or os.getcwd()
    if local is None:
        local = {"local:heretic": _heretic_raw, "local:ask_local": run_ask_local}
    refused = _refused(cwd, prompt)
    routing = load_routing()
    tier = task or routing["default"]
    if model:
        if refused and not model.startswith(LOCAL_PREFIX):
            return refused
        models = [model]
    elif tier in routing["tiers"]:
        models = routing["tiers"][tier]
        if refused:  # nothing may leave the machine: only local entries remain
            models = [m for m in models if m.startswith(LOCAL_PREFIX)]
            if not models:
                return refused
    else:
        if refused:
            return refused
        return {"ok": False, "error": f"unknown task {tier!r}",
                "detail": f"use one of: {', '.join(routing['tiers'])}"}
    quota = read_quota()
    skipped = []
    for m in models:
        if m.startswith(LOCAL_PREFIX):
            if edits or _PATHLIKE.search(prompt):
                if model:
                    return {"ok": False, "error": _LOCAL_CANNOT, "model": m}
                skipped.append({"model": m, "reason": _LOCAL_CANNOT})
                continue
            out = _call_local(m, prompt, local)
            if out["ok"] or model:
                if skipped:
                    out["skipped"] = skipped
                return out
            skipped.append({"model": m, "reason": out["error"]})
            continue
        if not model and m in quota:
            skipped.append({"model": m, "reason": f"exhausted until {_iso(quota[m])}"})
            continue
        started = time.time()
        out = ask(prompt, cwd=cwd, edits=edits, timeout=timeout or AGY_TIMEOUT, model=m)
        out = {k: v for k, v in out.items() if v is not None and v != [] and v != {} and v != ""}
        out["ok"] = bool(out.get("ok"))
        out["model"] = m
        if not out["ok"]:
            log_path = _copy_agy_log(m, started, out.get("conversation_id"))
            if log_path:
                out["log"] = log_path
        _log("agy", m, started, out)
        if _is_exhausted(out):
            mark_exhausted(m, f"{out.get('error', '')} {out.get('detail', '')} {out.get('response', '')}")
            if model:  # explicit model: report its own result, no fallback
                out["hint"] = _STATUS_ERROR_HINT
                return out
            skipped.append({"model": m, "reason": "quota exhausted"})
            continue
        if out.get("error") == "status ERROR":
            out["hint"] = _STATUS_ERROR_HINT
        if skipped:
            out["skipped"] = skipped
        return out
    if refused:
        return {**refused, "skipped": skipped}
    return {"ok": False, "error": f"all models in tier {tier} exhausted", "skipped": skipped,
            "hint": "fall back to ask_heretic / ask_local, or do it yourself"}


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
    started = time.time()
    out = _heretic_raw(prompt, system, think)
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


def agy_models() -> dict:
    """Per tier, the first model not marked exhausted; plus {model: ISO reset time}. No pings."""
    routing, quota = load_routing(), read_quota()
    return {"tiers": {t: next((m for m in ms if m not in quota), None)
                      for t, ms in routing["tiers"].items()},
            "exhausted": {m: _iso(u) for m, u in sorted(quota.items())}}


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
        "agy_models": agy_models(),
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
    def _agy(prompt: str, cwd: str | None = None, task: str | None = None,
             model: str | None = None, timeout: int | None = None, edits: bool = False) -> dict:
        """Run one prompt in Antigravity CLI. agy reads files and calls the stack's MCP servers
        read-only; edits=True lets it write inside cwd. Default cwd is the session's project.
        task picks the model, falling back when a quota is spent: light=trivial lookups/summaries,
        tried first on Heretic then the local Ollama model (free; only for prompts naming no
        file path and without edits), then Gemini Flash low; code=default, ordinary coding and
        research; hard=deep reasoning (Opus first); review=second opinion on Claude's work
        (non-Claude first). model overrides task ("local:heretic" / "local:ask_local" too).
        In a local-only directory only the local models run."""
        return run_agy(prompt, cwd, model, timeout, edits, task=task)

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

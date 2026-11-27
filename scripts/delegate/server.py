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
- ask_codex:   OpenAI Codex CLI (`codex exec --json --ephemeral`) on the ChatGPT login in
               ~/.codex, run inside the agy jail (features/antigravity/agy-jail) with Codex's
               own read-only or workspace-write sandbox nested in it. CODEX_BIN, DELEGATE_CODEX_MODEL
               and DELEGATE_CODEX_TIMEOUT (default 600 s) tune it. A usage-limit failure is
               recorded as "codex" in state/agy-quota.json and skipped until reset.
- ask_heretic: the local llama-server (Heretic) on :8090. Nothing leaves the machine.
- ask_openai:  any OpenAI-compatible API. Off until the env var named by
               DELEGATE_OPENAI_KEY_ENV (default OPENAI_API_KEY) holds a key and
               DELEGATE_OPENAI_MODEL names a model; DELEGATE_OPENAI_URL picks the endpoint.
- make_image / make_video / speak: ComfyUI and Chatterbox, through scripts/local_chat.

Off-machine backends (agy, codex, openai) refuse when the working directory, or any path named in
the prompt, is under a root listed in config/delegate-local-only.txt or DELEGATE_LOCAL_ONLY
(os.pathsep separated). Claude Code starts stdio servers in the session's project
directory, so a session inside a local-only repo can't ship it to Google or OpenAI.

Every call is logged to state/delegate.jsonl (backend, model, seconds, ok; no content).
"""
import datetime
import difflib
import fnmatch
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ask_agy  # noqa: E402
import brief_lint  # noqa: E402

AGY_MODEL = os.environ.get("DELEGATE_AGY_MODEL", "gemini-3.8-flash-medium")
AGY_TIMEOUT = int(os.environ.get("DELEGATE_AGY_TIMEOUT", "300"))
# Claude Code aborts an MCP call that sends "no response or progress for 1800s" (two mtw2 edit jobs
# lost that way on 2026-11-20). The agy tools ping progress every PING_S while agy runs; when the
# client gave no progress token there is nothing to ping, so the agy timeout is clamped under the
# client's idle limit instead and the call returns agy's own timeout result, not nothing.
CLIENT_IDLE_S = int(os.environ.get("DELEGATE_CLIENT_IDLE_S", "1800"))
IDLE_MARGIN_S = 120
PING_S = 60.0
_AGY_LOCK = threading.Lock()  # one agy job at a time, as when the tools blocked the event loop
_CODEX_LOCK = threading.Lock()  # one Codex job at a time; it runs alongside agy, not behind it
CODEX_MODEL = os.environ.get("DELEGATE_CODEX_MODEL", "")  # empty: Codex's own default for the plan
CODEX_TIMEOUT = int(os.environ.get("DELEGATE_CODEX_TIMEOUT", "600"))
CODEX_QUOTA_KEY = "codex"  # in state/agy-quota.json, so a spent ChatGPT window is skipped until reset
_CODEX_LIMIT_RE = re.compile(r"usage limit|rate limit|too many requests|\b429\b", re.I)
OPENAI_URL = os.environ.get("DELEGATE_OPENAI_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.environ.get("DELEGATE_OPENAI_MODEL", "")
OPENAI_KEY_ENV = os.environ.get("DELEGATE_OPENAI_KEY_ENV", "OPENAI_API_KEY")
LOCAL_ONLY_FILE = _REPO / "config" / "delegate-local-only.txt"
ROUTING_FILE = _REPO / "config" / "delegate-routing.json"
PACKET_ALLOW_FILE = _REPO / "config" / "delegate-packet-allow.txt"
PACKET_ALLOW_LOCAL_FILE = _REPO / "config" / "delegate-packet-allow.local.txt"  # gitignored; this repo is public
PACKET_WORDS = Path("private") / "packet-refuse-words.txt"  # inside the repo the files come from
PERMISSIONS_FILE = _REPO / "features" / "antigravity" / "permissions.json"
# agy's read rules allow this tree, so the throwaway copies live inside it
PACKET_ROOT = Path(os.environ.get("DELEGATE_PACKET_ROOT") or f"/tmp/claude-{os.getuid()}/agy-packets")
PACKET_MAX_BYTES = 500_000
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


def _log(backend: str, model: str | None, started: float, out: dict, cwd: str | None = None) -> None:
    if LOG_PATH is None:
        return
    call_cwd = cwd or os.getcwd()
    project = os.path.basename(os.path.normpath(call_cwd))
    rec = {"ts": round(time.time(), 1), "backend": backend, "model": model,
           "project": project,
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
            pools = [[m for m in pool if isinstance(m, str) and m]
                     for pool in data.get("quota_pools", []) if isinstance(pool, list)]
            pools = [p for p in pools if p]
            return {
                "default": default if default in tiers else next(iter(tiers)),
                "tiers": tiers,
                "quota_pools": pools,
            }
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        pass
    return {"default": "code", "tiers": {"code": [AGY_MODEL]}, "quota_pools": []}


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


def mark_exhausted(model: str, text: str = "", now: float | None = None,
                   pools: list[list[str]] | None = None) -> float:
    """Record model as exhausted until the reset time in text; atomic write. Returns until."""
    now = time.time() if now is None else now
    until = now + reset_seconds(text)
    if pools is None:
        pools = load_routing().get("quota_pools", [])
    models_to_mark = [model]
    for pool in pools:
        if model in pool:
            for member in pool:
                if member not in models_to_mark:
                    models_to_mark.append(member)
    quota = read_quota(now)
    for m in models_to_mark:
        quota[m] = until
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


def _call_local(name: str, prompt: str, local: dict, cwd: str | None = None) -> dict:
    fn = local.get(name)
    if fn is None:
        return {"ok": False, "error": f"unknown local backend {name!r}", "model": name}
    started = time.time()
    try:
        raw = fn(prompt)
    except Exception as e:  # noqa: BLE001 — a broken local backend must fall through, not crash
        raw = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    out = _local_result(name, raw)
    _log("local", name, started, out, cwd=cwd)
    return out


def run_agy(prompt: str, cwd: str | None = None, model: str | None = None,
            timeout: int | None = None, edits: bool = False, ask=ask_agy.ask,
            task: str | None = None, local: dict | None = None) -> dict:
    cwd = cwd or os.getcwd()
    if local is None:
        local = {"local:heretic": _heretic_raw, "local:ask_local": run_ask_local}
    refused = _refused(cwd, prompt)
    if problems := brief_lint.lint(prompt, cwd):
        # agy would hit these denials mid-run and burn quota (2 failed jobs, 11-01); say so now
        out = {"ok": False, "error": "brief_lint", "problems": problems,
               "hint": "rewrite the brief: bare commands, no branching, paste out-of-repo content; "
                       "have agy read checks and run them yourself"}
        _log("agy", model, time.time(), out, cwd=cwd)
        return out
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
            out = _call_local(m, prompt, local, cwd=cwd)
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
        if isinstance(out, dict):
            ask_agy.log_denials(out, os.path.basename(os.path.normpath(cwd or os.getcwd())))
        out = {k: v for k, v in out.items() if v is not None and v != [] and v != {} and v != ""}
        out["ok"] = bool(out.get("ok"))
        out["model"] = m
        if not out["ok"]:
            log_path = _copy_agy_log(m, started, out.get("conversation_id"))
            if log_path:
                out["log"] = log_path
        _log("agy", m, started, out, cwd=cwd)
        if _is_exhausted(out):
            pools = routing.get("quota_pools", [])
            until = mark_exhausted(m, f"{out.get('error', '')} {out.get('detail', '')} {out.get('response', '')}",
                                   pools=pools)
            quota = read_quota()
            for pool in pools:
                if m in pool:
                    for member in pool:
                        quota[member] = until
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


def _secret_globs() -> list[str]:
    """The filename patterns agy itself may never read, such as key files. Raises if they can't be read."""
    deny = json.loads(PERMISSIONS_FILE.read_text()).get("deny", [])
    rules = [r[len("read_file("):-1] for r in deny if isinstance(r, str) and r.startswith("read_file(")]
    return [r for r in rules if "*" in r]


def _read_no_follow(path: Path) -> bytes:
    """Read a regular file. A symlink swapped in since the check raises OSError."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        return f.read()


def _refuse_words(base: Path) -> list[str]:
    """Names that must not leave this repo, casefolded. Raises OSError if the list can't be read."""
    lines = (base / PACKET_WORDS).read_text(encoding="utf-8").splitlines()
    return [word for word in (line.split("#", 1)[0].strip().casefold() for line in lines) if word]


def _names_hit(text: str, words: list[str]) -> bool:
    folded = text.casefold()
    return any(word in folded for word in words)


def _packet_contents(base: Path, files: list[str]) -> tuple[dict[str, bytes], dict | None]:
    """The files' contents by relative path, or a refusal. One bad name refuses the whole packet.
    Each file is read as it's checked, so nothing can be swapped in between the check and the copy."""
    if not files:
        return {}, {"ok": False, "error": "no_files", "detail": "name the files to send"}
    try:
        secret = _secret_globs()
    except (OSError, ValueError, AttributeError, TypeError) as err:  # no list of secrets, so nothing goes
        return {}, {"ok": False, "error": "deny_rules_unreadable", "detail": str(err)[:200]}
    try:
        words = _refuse_words(base)
    except (OSError, ValueError) as err:
        words, why = [], str(err)[:200]
    else:
        why = "the list is empty"
    if not words:  # nothing to check against, so nothing goes
        return {}, {"ok": False, "error": "no_names_list", "detail": f"{PACKET_WORDS}: {why}"}
    allowed = local_only_roots(PACKET_ALLOW_FILE, env="") + local_only_roots(PACKET_ALLOW_LOCAL_FILE, env="")
    contents, total = {}, 0
    for name in files:
        no = {"ok": False, "error": "not_allow_listed",
              "detail": f"{name[:200]!r} isn't in {PACKET_ALLOW_FILE.name}; use ask_heretic or do it yourself"}
        try:
            real = (base / name).resolve()  # resolving catches ../ and symlinks that point elsewhere
            if base not in real.parents or not _under(real, allowed):
                return {}, no
            if any(fnmatch.fnmatch(str(real), g) for g in secret):
                return {}, no
            if not real.is_file():
                return {}, {"ok": False, "error": "file_not_found", "detail": name[:200]}
            rel = str(real.relative_to(base))
            data = _read_no_follow(real)
        except (OSError, ValueError):  # a null byte, an overlong name, an unreadable file, a swapped-in link
            return {}, no
        try:
            text = data.decode()
        except UnicodeDecodeError:  # the names scan can't be trusted on bytes it can't read
            return {}, {"ok": False, "error": "not_text", "detail": f"{rel} isn't UTF-8 text"}
        if _names_hit(rel, words) or _names_hit(text, words):
            return {}, {"ok": False, "error": "names_hit", "detail": f"{rel} contains a name on {PACKET_WORDS}"}
        contents[rel] = data
        total += len(data)
    if total > PACKET_MAX_BYTES:
        return {}, {"ok": False, "error": "packet_too_large", "detail": f"{total} bytes, limit {PACKET_MAX_BYTES}"}
    return contents, None


def _snapshot(folder: Path) -> dict[str, bytes]:
    """Exact bytes, so binary and line-ending edits count as changes. A symlink is reported by name
    and never followed, so the agent can't pull an outside file into the diff."""
    seen = {}
    for p in folder.rglob("*"):
        name = str(p.relative_to(folder))
        if p.is_symlink():
            seen[name] = f"symlink to {os.readlink(p)}\n".encode()
        elif p.is_file():
            try:
                seen[name] = p.read_bytes()
            except OSError as err:  # one unreadable file mustn't lose the rest of the result
                seen[name] = f"unreadable: {err.strerror}\n".encode()
    return seen


def _packet_diff(name: str, old: bytes, new: bytes) -> list[str]:
    try:
        old_text, new_text = old.decode(), new.decode()
    except UnicodeDecodeError:
        return [f"Binary file {name} differs\n"]
    return list(difflib.unified_diff(old_text.splitlines(True), new_text.splitlines(True),
                                     f"a/{name}", f"b/{name}"))


def run_agy_packet(prompt: str, files: list[str], base: str, task: str | None = None,
                   model: str | None = None, timeout: int | None = None, ask=ask_agy.ask) -> dict:
    """Run agy on a throwaway copy of the named files and return its changes as a diff."""
    root = Path(base).resolve()
    contents, refused = _packet_contents(root, files)
    if refused := refused or _refused(str(PACKET_ROOT), prompt):
        return refused
    try:
        hit = _names_hit(prompt, _refuse_words(root))
    except (OSError, ValueError) as err:  # the list vanished since the files were checked
        return {"ok": False, "error": "no_names_list", "detail": str(err)[:200]}
    if hit:
        return {"ok": False, "error": "names_hit", "detail": f"the prompt contains a name on {PACKET_WORDS}"}
    try:
        PACKET_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        if PACKET_ROOT.is_symlink() or PACKET_ROOT.stat().st_uid != os.getuid():
            return {"ok": False, "error": "packet_root_unusable", "detail": f"{PACKET_ROOT} isn't this user's folder"}
        PACKET_ROOT.chmod(0o700)
        with tempfile.TemporaryDirectory(dir=PACKET_ROOT, ignore_cleanup_errors=True) as temp:
            work = Path(temp) / root.name  # the folder's name is what the call log records as the project
            work.mkdir()
            for name, data in contents.items():
                (work / name).parent.mkdir(parents=True, exist_ok=True)
                (work / name).write_bytes(data)
            before = _snapshot(work)
            out = run_agy(prompt, str(work), model, timeout, edits=True, ask=ask, task=task)
            after = _snapshot(work)
    except OSError as err:
        return {"ok": False, "error": "packet_root_unusable", "detail": str(err)[:200]}
    changed = sorted(n for n in before.keys() | after.keys() if before.get(n) != after.get(n))
    diff = [line for n in changed for line in _packet_diff(n, before.get(n, b""), after.get(n, b""))]
    result = {**out, "diff": "".join(diff), "changed": changed}
    added = "\n".join(line[1:] for line in diff if line.startswith("+") and not line.startswith("+++"))
    if echoes := brief_lint.echoed_runs(prompt, added):
        result["brief_echoes"] = echoes[:10]
        result["warning"] = (f"{len(echoes)} run(s) of 8+ words were copied from the brief into the files; "
                             "read them: a brief's example phrases are not the text to write")
    return result


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
    _log("openai", model, started, out, cwd=cwd)
    return out


def codex_bin() -> str | None:
    """CODEX_BIN, else codex on PATH, else npm's user prefix (often not on the server's PATH).

    Must be named codex: the jail picks which login to mount by that name, so a wrapper named
    anything else would get agy's login and not Codex's."""
    for c in (os.environ.get("CODEX_BIN"), shutil.which("codex"),
              str(Path.home() / ".npm-global" / "bin" / "codex")):
        if c and os.path.basename(c) == "codex" and os.access(c, os.X_OK):
            return c
    return None


def codex_logged_in() -> bool:
    return (Path.home() / ".codex" / "auth.json").is_file()


def codex_cmd(binary: str, cwd: str, model: str | None, edits: bool) -> list[str]:
    cmd = [binary, "exec", "--json", "--ephemeral", "--skip-git-repo-check",
           "--sandbox", "workspace-write" if edits else "read-only", "-C", cwd]
    if model:
        cmd += ["-m", model]
    return cmd + ["-"]  # prompt on stdin: no argv length limit, not visible in ps


def parse_codex_events(stdout: str) -> dict:
    """The answer, usage, thread id and errors from `codex exec --json` lines.

    Unknown or malformed lines are skipped, so a schema change after an upgrade reads as no
    answer (and fails closed in run_codex), never as a made-up one."""
    out: dict = {"messages": [], "errors": [], "warnings": [], "commands": 0}
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(ev, dict):
            continue
        kind = ev.get("type", "")
        item = ev.get("item") if isinstance(ev.get("item"), dict) else {}
        if kind == "turn.completed":
            out["completed"] = True
        if kind == "thread.started":
            out["thread_id"] = ev.get("thread_id")
        elif kind == "item.completed" and item.get("type") == "agent_message":
            if isinstance(item.get("text"), str) and item["text"].strip():
                out["messages"].append(item["text"].strip())
        elif kind == "item.completed" and item.get("type") == "command_execution":
            out["commands"] += 1
        elif kind == "turn.completed" and isinstance(ev.get("usage"), dict):
            out["usage"] = ev["usage"]
        elif kind in ("turn.failed", "error"):
            err = ev.get("error") if isinstance(ev.get("error"), dict) else ev
            msg = str((err.get("message") if isinstance(err, dict) else None) or line)[:500]
            # "error" events include retries Codex recovers from ("Reconnecting... 3/5");
            # only a failed turn fails the job
            out["errors" if kind == "turn.failed" else "warnings"].append(msg)
    return out


def run_codex(prompt: str, cwd: str | None = None, model: str | None = None,
              timeout: int | None = None, edits: bool = False, run=subprocess.run) -> dict:
    """One `codex exec` job inside the agy jail, on the ChatGPT subscription login."""
    cwd = os.path.realpath(cwd or os.getcwd())
    model = model or CODEX_MODEL or None
    label = model or "codex-default"
    if refused := _refused(cwd, prompt):
        return refused
    binary = codex_bin()
    if not binary:
        return {"ok": False, "error": "not_installed",
                "detail": "npm i -g @openai/codex (or set CODEX_BIN)"}
    if not codex_logged_in():
        return {"ok": False, "error": "not_logged_in", "detail": "run `codex login` once on this host"}
    quota = read_quota()
    if CODEX_QUOTA_KEY in quota:
        return {"ok": False, "error": "quota exhausted", "model": label,
                "detail": f"Codex usage limit; skipped until {_iso(quota[CODEX_QUOTA_KEY])}",
                "hint": "fall back to ask_agy / ask_heretic, or do it yourself"}
    cmd = ask_agy.jailed(codex_cmd(binary, cwd, model, edits), cwd)
    if cmd is None:
        return {"ok": False, "error": "no jail",
                "detail": f"needs bubblewrap and {ask_agy.JAIL}; refusing to run Codex outside the jail"}
    env = {**os.environ, "PATH": f"{Path(binary).parent}{os.pathsep}{os.environ.get('PATH', '')}"}
    saved, dest, snap_errors = [], None, []
    if edits:
        try:
            ask_agy.BACKUPS.mkdir(parents=True, exist_ok=True)
            dest = Path(tempfile.mkdtemp(prefix=time.strftime("codex-%Y%m%d-%H%M%S-"), dir=ask_agy.BACKUPS))
            saved = ask_agy.snapshot_uncommitted(cwd, dest, snap_errors)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            snap_errors.append(str(exc)[:300])
    started = time.time()
    t = timeout or CODEX_TIMEOUT
    try:
        proc = run(cmd, input=prompt, cwd=cwd, capture_output=True, text=True, timeout=t, env=env)
    except subprocess.TimeoutExpired:
        out = {"ok": False, "error": f"timeout after {t}s", "model": label}
        proc = None
    except (OSError, ValueError) as e:  # ValueError: a NUL byte in model or cwd
        out = {"ok": False, "error": f"codex failed to start: {e}", "model": label}
        proc = None
    if proc is not None:
        ev = parse_codex_events(proc.stdout or "")
        answer = ev["messages"][-1] if ev["messages"] else ""
        # a finished turn, not just a message: a run cut off mid-turn can still have said something
        out = {"ok": proc.returncode == 0 and bool(answer) and not ev["errors"] and bool(ev.get("completed")),
               "response": answer, "model": label, "usage": ev.get("usage"),
               "thread_id": ev.get("thread_id"), "commands_run": ev["commands"]}
        if not out["ok"]:
            stderr_tail = (proc.stderr or "").strip()[-800:]
            out["error"] = (ev["errors"][-1] if ev["errors"] else
                            ev["warnings"][-1] if ev["warnings"] else
                            f"exit {proc.returncode}" if proc.returncode else "no_answer")
            if stderr_tail:
                out["stderr"] = stderr_tail
            if not ev["messages"] and not ev["errors"] and not ev["warnings"]:
                out["stdout_tail"] = (proc.stdout or "")[-800:]
            text = f"{out['error']} {stderr_tail}"
            if _CODEX_LIMIT_RE.search(text):
                until = mark_exhausted(CODEX_QUOTA_KEY, text, pools=[])
                out["hint"] = f"Codex usage limit; skipping Codex until {_iso(until)}"
        out = {k: v for k, v in out.items() if v is not None and v != ""}
    if edits:
        if snap_errors:
            out["snapshot_error"] = "; ".join(snap_errors)[:600]
        hits = ask_agy.changed_since(saved) if saved else []
        if hits:
            out["overwrote_uncommitted"] = hits
            out["warning"] = (f"Codex changed {len(hits)} file(s) that already had uncommitted changes; "
                              "if you didn't ask it to, restore from the backups in overwrote_uncommitted")
        elif dest:
            shutil.rmtree(dest, ignore_errors=True)
    _log("codex", label, started, out, cwd=cwd)
    return out


def run_heretic(prompt: str, system: str | None = None, think: bool = False, cwd: str | None = None) -> dict:
    started = time.time()
    out = _heretic_raw(prompt, system, think)
    _log("heretic", "heretic", started, out, cwd=cwd)
    return out


_SEED_RE = re.compile(r"\bseed (\d+)")


def media_args(width: int | None = None, height: int | None = None, seed: int | None = None,
               ref_image: str | list[str] | None = None, denoise: float | None = None,
               model: str | None = None) -> list[str] | dict:
    """comfy_job.py options for make_image's extras, or {"error": ...} for a bad ref path."""
    args: list[str] = []
    for flag, v in (("--width", width), ("--height", height), ("--seed", seed),
                    ("--denoise", denoise), ("--model", model)):
        if v is not None:
            args += [flag, str(v)]
    refs = [ref_image] if isinstance(ref_image, str) else list(ref_image or [])
    for r in refs:
        ref = Path(r).expanduser()
        if not ref.is_absolute():
            return {"ok": False, "error": f"ref_image must be an absolute path: {r}"}
        args += ["--ref", str(ref)]
    return args


def run_media(kind: str, prompt: str, cwd: str | None = None,
              extra: list[str] | None = None) -> dict:
    lc = local_chat()
    started = time.time()
    if kind == "speak":
        out = lc.speak(prompt)
    else:
        # "--" so a prompt starting with "-" is never read as an option
        r = lc._run([sys.executable, str(_REPO / "scripts" / "comfy_job.py"), kind,
                     *(extra or []), "--", prompt], timeout=lc.JOB_TIMEOUT[kind])
        files = [p for p in r["output"].splitlines()
                 if p.startswith(str(lc.OUTPUTS)) and lc.media_kind(p)]
        out = {"ok": r["ok"] and bool(files), "files": files}
        seeds = _SEED_RE.findall(r["output"])
        if seeds:
            out["seed"] = int(seeds[-1])
        if not out["ok"]:
            out["error"] = r["output"][-1500:]
    _log(kind, None, started, out, cwd=cwd)
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
        "codex": {"installed": bool(codex_bin()), "logged_in": codex_logged_in(),
                  "model": CODEX_MODEL or "codex-default",
                  "exhausted_until": _iso(q) if (q := read_quota().get(CODEX_QUOTA_KEY)) else None},
        "openai": "configured" if os.environ.get(OPENAI_KEY_ENV) and OPENAI_MODEL else "not_configured",
        "cwd": cwd,
        "local_only": local_only_block(cwd),
    }


def has_progress_token(ctx) -> bool:
    """Did the client ask for progress on this call? (FastMCP's report_progress is a no-op without.)"""
    try:
        meta = ctx.request_context.meta
    except Exception:  # no request in flight (tests, direct calls)
        return False
    return bool(meta is not None and getattr(meta, "progressToken", None) is not None)


def clamp_timeout(timeout: int | None, pinging: bool) -> tuple[int, int | None]:
    """(timeout to use, the asked-for timeout when it was clamped, else None)."""
    t = timeout or AGY_TIMEOUT
    cap = CLIENT_IDLE_S - IDLE_MARGIN_S
    return (t, None) if pinging or t <= cap else (cap, t)


async def keep_alive(ctx, pinging: bool, fn, *args, lock=None, label: str = "agy", **kwargs):
    """Run blocking fn in a worker thread under _AGY_LOCK; while it runs, send a progress
    notification every PING_S so the client's idle timer doesn't abort the call. A failed ping
    (client gone, stream closed) stops the pinging and never costs the result."""
    import anyio

    done = anyio.Event()

    async def pinger():
        n = 0
        while True:
            with anyio.move_on_after(PING_S):
                await done.wait()
            if done.is_set():
                return
            n += 1
            try:
                await ctx.report_progress(n, message=f"{label} still running ({round(n * PING_S)} s)")
            except Exception:
                return

    def locked():
        with lock or _AGY_LOCK:
            return fn(*args, **kwargs)

    box = {}
    async with anyio.create_task_group() as tg:
        if pinging:
            tg.start_soon(pinger)
        try:
            box["result"] = await anyio.to_thread.run_sync(locked)
        except Exception as e:  # raised after the group closes, so callers see it unwrapped
            box["error"] = e
        finally:
            done.set()
    if "error" in box:
        raise box["error"]
    return box["result"]


async def _agy_tool(ctx, run, timeout, *args, lock=None, label: str = "agy", **kwargs) -> dict:
    pinging = has_progress_token(ctx)
    t, asked = clamp_timeout(timeout, pinging)
    out = await keep_alive(ctx, pinging, run, *args, lock=lock, label=label, timeout=t, **kwargs)
    if isinstance(out, dict):
        if not pinging:
            out["no_progress_token"] = True
        if asked is not None:
            out["timeout_clamped"] = {"asked": asked, "used": t, "client_idle_s": CLIENT_IDLE_S}
    return out


def build_server():
    from mcp.server.fastmcp import Context, FastMCP

    mcp = FastMCP("delegate", log_level="WARNING", instructions=(
        "Hand work to a model other than Claude: Gemini via agy (subscription quota, off "
        "machine), OpenAI Codex via ask_codex (ChatGPT subscription, off machine), Heretic (local, private, uncensored), an OpenAI-compatible API when "
        "configured, and local image/video/speech. Decide the check before delegating and run "
        "it on what comes back (verifiable-task skill); a helper's own 'done' is not evidence. "
        "agy/codex/openai refuse inside local-only repos."))

    @mcp.tool(name="delegate_status")
    def _status() -> dict:
        """Which delegate backends are usable here, and whether this directory is local-only."""
        return status()

    @mcp.tool(name="ask_agy")
    async def _agy(ctx: Context, prompt: str, cwd: str | None = None, task: str | None = None,
                   model: str | None = None, timeout: int | None = None, edits: bool = False) -> dict:
        """Run one prompt in Antigravity CLI. agy reads files and calls the stack's MCP servers
        read-only; edits=True lets it write inside cwd. Default cwd is the session's project.
        task picks the model, falling back when a quota is spent: light=trivial lookups/summaries,
        tried first on Heretic then the local Ollama model (free; only for prompts naming no
        file path and without edits), then Gemini Flash low; code=default, ordinary coding and
        research; hard=deep reasoning (Opus first); review=second opinion on Claude's work
        (non-Claude first). model overrides task ("local:heretic" / "local:ask_local" too).
        In a local-only directory only the local models run. Long jobs send progress every 60 s;
        a client that takes no progress gets timeout clamped under its idle limit
        (timeout_clamped in the result)."""
        return await _agy_tool(ctx, run_agy, timeout, prompt, cwd, model, edits=edits, task=task)

    @mcp.tool(name="ask_agy_packet")
    async def _agy_packet(ctx: Context, prompt: str, files: list[str], base: str | None = None,
                          task: str | None = None, model: str | None = None,
                          timeout: int | None = None) -> dict:
        """Run agy on a throwaway copy of the named files, and return `diff` and `changed` for you to
        review and apply. Live files are never touched. files are relative to base (default: the
        session's project). Each must be under config/delegate-packet-allow.txt or its .local.txt, and
        be UTF-8 text with nothing from the repo's private/packet-refuse-words.txt, or the whole call
        is refused. This limits which files you hand over, not what agy can reach: it keeps its other
        tools. Name files by relative path in the prompt, and keep private details out of it."""
        return await _agy_tool(ctx, run_agy_packet, timeout, prompt, files, base or os.getcwd(),
                               task, model)

    @mcp.tool(name="ask_codex")
    async def _codex(ctx: Context, prompt: str, cwd: str | None = None, model: str | None = None,
                     timeout: int | None = None, edits: bool = False) -> dict:
        """Run one prompt in OpenAI Codex CLI (`codex exec`) on the ChatGPT subscription. Codex reads
        files and runs shell commands in its own sandbox, inside the same empty-root jail as agy:
        it sees only cwd's repo. Read-only by default; edits=True lets it write inside the repo
        (uncommitted files are backed up, overwrote_uncommitted says if it touched them). No stack
        MCP servers. model: a Codex model id, default the plan's own. Refuses in local-only
        directories. A spent usage limit is remembered and skipped until reset (default 1 h)."""
        return await _agy_tool(ctx, run_codex, timeout, prompt, cwd, model, edits=edits,
                               lock=_CODEX_LOCK, label="codex")

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
    def _image(prompt: str, width: int | None = None, height: int | None = None,
               seed: int | None = None, ref_image: str | list[str] | None = None,
               model: str = "auto", denoise: float | None = None) -> dict:
        """Text-to-image or reference edit on ComfyUI (~1-2 min). Returns file paths and seed.

        No ref_image: Z-Image-Turbo text-to-image. ref_image (absolute path, or a list of up
        to 4) with model "auto"/"klein": FLUX.2 klein 4B edit; the prompt calls them image 1,
        image 2, ... and can put their characters into a new scene ("the six people from image
        1 walking along a riverbank"). model "z-image" with one ref: img2img, denoise 0-1
        (default 0.6), keeps layout/colours only, for small variations of one picture.
        model "qwen" with 1-3 refs (prompt calls them Picture 1-3): Qwen-Image-Edit-2511,
        keeps several characters' faces and outfits apart far better than klein; ~3 min,
        refuses below 20 GiB free RAM and always waits for Klarheit's trials. One ref per
        visible character; describe outfits literally; negations get drawn.
        width/height: multiples of 16, 256-2048 (default 1024x1024, or the first reference's
        aspect at ~1 MP). seed: reuse one from an earlier result to vary only the prompt.
        """
        extra = media_args(width, height, seed, ref_image, denoise,
                           None if model == "auto" else model)
        if isinstance(extra, dict):
            return extra
        return run_media("image", prompt, extra=extra)

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

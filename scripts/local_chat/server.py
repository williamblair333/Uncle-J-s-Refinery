#!/usr/bin/env python3
"""Local chat page: start/stop/log the heretic server and chat with it, Claude or agy.

Usage:
  server.py [--port 8091]

Serves one page on 127.0.0.1 only. Conversations are saved as JSONL under
state/local_chat/, one file per conversation. Backends:

- heretic: llama-server at ASK_LOCAL_URL (default http://127.0.0.1:8090), full history sent;
- claude:  `claude -p` on your login, with no tools, no hooks and no saved session;
- agy:     scripts/ask_agy.py's ask() under its read-only allow list.

Claude and agy get the conversation as one transcript prompt, so any of them can pick
up where another left off.

"Search the web" queries SearXNG (SEARXNG_URL, default http://127.0.0.1:8086, JSON format
enabled) with your message and hands the top results to whichever backend answers.
Start uses `dcup up` when dcup is installed, so heretic's port is claimed in the registry.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ask_agy  # noqa: E402

HERE = Path(__file__).resolve().parent
CHATS = ROOT / "state" / "local_chat"
COMPOSE_FILE = str(ROOT / "docker" / "llama-heretic" / "compose.yaml")
COMPOSE = ["docker", "compose", "-f", COMPOSE_FILE]
DCUP = shutil.which("dcup") or next(
    (p for p in ["/opt/lib/docker-port-registry/dcup"] if os.access(p, os.X_OK)), None)
LLAMA_URL = os.environ.get("ASK_LOCAL_URL", "http://127.0.0.1:8090").rstrip("/")
SEARX_URL = os.environ.get("SEARXNG_URL", "http://127.0.0.1:8086").rstrip("/")
SEARCH_RESULTS = 5
CHAT_ID = re.compile(r"^[0-9a-f]{32}$")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")  # compose logs keep line-erase codes despite --no-color
TIMEOUT = 600
# Each send is a fresh Claude Code session: without this, your SessionStart/Stop hooks
# (Telegram, memweave mining) fire on every message. --bare would skip them too, but it
# accepts only ANTHROPIC_API_KEY, not a subscription login.
CLAUDE_CMD = ["claude", "-p", "--settings", '{"disableAllHooks":true}', "--setting-sources", "project",
              "--tools", "", "--no-session-persistence", "--output-format", "text"]
HANDOFF = "Continue this conversation. Reply only as the assistant to the last USER turn.\n\n"


def _run(cmd, timeout=120, stdin=None, cwd=ROOT):
    try:
        p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except FileNotFoundError:
        return {"ok": False, "output": f"not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": f"timed out after {timeout}s"}
    return {"ok": p.returncode == 0, "output": (p.stdout + p.stderr).strip()}


def server_status():
    r = _run(["docker", "ps", "-a", "--filter", "name=^llama-heretic$", "--format", "{{.Status}}"], timeout=15)
    try:
        with urllib.request.urlopen(f"{LLAMA_URL}/health", timeout=3) as resp:
            healthy = resp.status == 200
    except (urllib.error.URLError, OSError):
        healthy = False
    return {"container": r["output"] or "not created", "healthy": healthy, "url": LLAMA_URL}


def web_search(query):
    url = f"{SEARX_URL}/search?" + urllib.parse.urlencode({"q": query[:400], "format": "json"})
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return {"ok": False, "error": f"SearXNG unreachable at {SEARX_URL}: {e}"}
    hits = [{"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": (r.get("content") or "")[:300]}
            for r in data.get("results", [])[:SEARCH_RESULTS]]
    return {"ok": True, "results": hits}


def with_sources(question, hits):
    lines = [f"[{i}] {h['title']} — {h['url']}\n{h['snippet']}" for i, h in enumerate(hits, 1)]
    return (f"{question}\n\n---\nWeb search results (today is {time.strftime('%Y-%m-%d')}):\n\n"
            + "\n\n".join(lines)
            + "\n\nUse these where they're relevant and cite them as [n]. If they don't answer "
              "the question, say so.")


def transcript(messages):
    return "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)


def ask_heretic(messages):
    body = json.dumps({"model": "heretic", "messages": messages, "max_tokens": 8192}).encode()
    req = urllib.request.Request(f"{LLAMA_URL}/v1/chat/completions", body,
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, OSError) as e:
        return {"ok": False, "error": f"heretic unreachable: {e}"}
    choice = data["choices"][0]
    text = (choice["message"].get("content") or "").strip()
    if not text:
        return {"ok": False, "error": f"empty answer (finish_reason {choice.get('finish_reason')})"}
    return {"ok": True, "text": text, "usage": data.get("usage")}


def ask_claude(messages):
    CHATS.mkdir(parents=True, exist_ok=True)
    r = _run(CLAUDE_CMD, timeout=TIMEOUT, stdin=HANDOFF + transcript(messages), cwd=CHATS)
    if not r["ok"] or not r["output"]:
        return {"ok": False, "error": r["output"] or "empty answer"}
    return {"ok": True, "text": r["output"]}


def ask_agy_backend(messages):
    out = ask_agy.ask(HANDOFF + transcript(messages), cwd=str(ROOT), timeout=TIMEOUT)
    if not out["ok"]:
        # ask() drops agy's own error text; "status ERROR" with zero tokens is almost always
        # an expired login, which only an interactive `agy` run can renew.
        hint = " (if agy isn't logged in, run `agy` once in a terminal)" if out.get("error") == "status ERROR" else ""
        return {"ok": False, "error": (out.get("error") or "agy failed") + hint}
    return {"ok": True, "text": out["response"], "usage": out.get("usage")}


BACKENDS = {"heretic": ask_heretic, "claude": ask_claude, "agy": ask_agy_backend}


def chat_path(chat_id):
    if not CHAT_ID.match(chat_id or ""):
        raise ValueError("bad chat id")
    return CHATS / f"{chat_id}.jsonl"


def load_chat(chat_id):
    p = chat_path(chat_id)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_chat(chat_id, entry):
    CHATS.mkdir(parents=True, exist_ok=True)
    with chat_path(chat_id).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def list_chats():
    out = []
    for p in sorted(CHATS.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        first = json.loads(lines[0]) if lines else {}
        out.append({"id": p.stem, "title": first.get("content", "")[:60], "mtime": p.stat().st_mtime})
    return out


def chat(body):
    chat_id = body.get("chat_id") or uuid.uuid4().hex
    backend = body.get("backend", "heretic")
    if backend not in BACKENDS:
        return {"ok": False, "error": f"unknown backend {backend}"}
    history = load_chat(chat_id)
    text = (body.get("text") or "").strip()
    if text:
        entry = {"role": "user", "content": text, "ts": time.time()}
        append_chat(chat_id, entry)
        history.append(entry)
    else:
        # No new text = hand your last question to this backend (a second opinion), so drop
        # the answers that followed it from what the backend sees.
        while history and history[-1]["role"] != "user":
            history.pop()
    if not history:
        return {"ok": False, "error": "nothing to answer yet", "chat_id": chat_id}
    # Second opinions leave several answers in a row; chat templates expect turns to alternate.
    messages = []
    for m in history:
        if messages and messages[-1]["role"] == m["role"]:
            messages[-1]["content"] += f"\n\n[another answer, from {m.get('backend', '?')}]\n{m['content']}"
        else:
            messages.append({"role": m["role"], "content": m["content"]})
    sources = None
    if body.get("web"):
        # Results go only into what the backend sees this turn; the saved question stays clean.
        found = web_search(messages[-1]["content"])
        if not found["ok"]:
            return {"ok": False, "error": found["error"], "chat_id": chat_id}
        sources = found["results"]
        if sources:
            messages[-1]["content"] = with_sources(messages[-1]["content"], sources)
    started = time.time()
    out = BACKENDS[backend](messages)
    if out["ok"]:
        entry = {"role": "assistant", "content": out["text"], "backend": backend,
                 "seconds": round(time.time() - started, 1), "ts": time.time()}
        if sources is not None:
            entry["sources"] = sources
        append_chat(chat_id, entry)
        out["sources"] = sources
    out["chat_id"] = chat_id
    out["backend"] = backend
    return out


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload, ctype="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass

    def _trusted(self):
        # A Host allow list stops DNS rebinding (evil.com resolving to 127.0.0.1); the Origin
        # check stops another site's page from POSTing here.
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in allowed:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin.removeprefix("http://") in allowed

    def do_GET(self):
        if not self._trusted():
            return self._send(403, {"error": "forbidden"})
        path, _, query = self.path.partition("?")
        try:
            if path == "/":
                return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/api/status":
                return self._send(200, server_status())
            if path == "/api/logs":
                r = _run(COMPOSE + ["logs", "--no-color", "--tail", "200"], timeout=30)
                r["output"] = ANSI.sub("", r["output"])
                return self._send(200, r)
            if path == "/api/chats":
                return self._send(200, list_chats())
            if path == "/api/chat":
                return self._send(200, load_chat(query.removeprefix("id=")))
        except ValueError as e:
            return self._send(400, {"ok": False, "error": str(e)})
        self._send(404, {"error": "not_found"})

    def do_POST(self):
        if not self._trusted():
            return self._send(403, {"error": "forbidden"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})
        try:
            if self.path == "/api/start":
                up = [DCUP, "-f", COMPOSE_FILE, "up", "-d"] if DCUP else COMPOSE + ["up", "-d"]
                return self._send(200, _run(up, timeout=300))
            if self.path == "/api/stop":
                return self._send(200, _run(COMPOSE + ["down"], timeout=120))
            if self.path == "/api/send":
                return self._send(200, chat(body))
        except ValueError as e:
            return self._send(400, {"ok": False, "error": str(e)})
        self._send(404, {"error": "not_found"})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8091)
    args = ap.parse_args(argv)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"local chat: http://127.0.0.1:{args.port}/", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()

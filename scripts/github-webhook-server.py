#!/usr/bin/env python3
"""
Uncle J's Refinery — GitHub Webhook Server

Pure Python stdlib. No external dependencies.
Config via .env in project root:
  GITHUB_WEBHOOK_SECRET   — required; shared secret set when registering webhook
  GITHUB_WEBHOOK_PORT     — port to listen on (default: 9000)
  GITHUB_REPO             — e.g. "williamblair333/Uncle-J-s-Refinery"
  CLAUDE_BIN              — path to claude CLI (default: claude)
  TELEGRAM_BOT_TOKEN      — for push notifications
  TELEGRAM_CHAT_ID        — for push notifications
"""

import hashlib
import hmac
import http.server
import json
import logging
import os
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJ_ROOT / ".env"
LOG_FILE = PROJ_ROOT / "state" / "github-webhook.log"


# ── Config ────────────────────────────────────────────────────────────────────

def load_env():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_env()

WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
WEBHOOK_PORT   = int(os.environ.get("GITHUB_WEBHOOK_PORT", "9000"))
GITHUB_REPO    = os.environ.get("GITHUB_REPO", "")
CLAUDE_BIN     = os.environ.get("CLAUDE_BIN", "claude")
TG_TOKEN       = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT        = os.environ.get("TELEGRAM_CHAT_ID", "")


# ── Logging ───────────────────────────────────────────────────────────────────

LOG_FILE.parent.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__).info
err = logging.getLogger(__name__).error


# ── Security ──────────────────────────────────────────────────────────────────

def verify_signature(payload: bytes, sig_header: str) -> bool:
    if not WEBHOOK_SECRET:
        log("WARNING: GITHUB_WEBHOOK_SECRET not set — accepting all requests")
        return True
    if not sig_header or not sig_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig_header)


# ── Delivery helpers ──────────────────────────────────────────────────────────

def telegram_send(text: str):
    if not TG_TOKEN or not TG_CHAT:
        return
    payload = json.dumps({
        "chat_id": TG_CHAT,
        "text": text[:4096],
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        err(f"Telegram error: {e}")


def github_comment(repo: str, pr_number: int, body: str):
    try:
        result = subprocess.run(
            ["gh", "pr", "comment", str(pr_number), "--repo", repo, "--body", body],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            err(f"gh comment failed: {result.stderr.strip()}")
    except Exception as e:
        err(f"GitHub comment error: {e}")


# ── Claude invocation ─────────────────────────────────────────────────────────

def run_claude(prompt: str) -> str:
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True, timeout=180, cwd=PROJ_ROOT,
        )
        return (result.stdout or result.stderr or "(no output)").strip()
    except subprocess.TimeoutExpired:
        return "⏱ Timed out (180s)."
    except Exception as e:
        return f"❌ Error running claude: {e}"


# ── Pre-script: fetch PR diff ─────────────────────────────────────────────────

def fetch_pr_diff(repo: str, pr_number: int) -> str:
    try:
        result = subprocess.run(
            ["gh", "pr", "diff", str(pr_number), "--repo", repo],
            capture_output=True, text=True, timeout=30,
        )
        diff = result.stdout.strip()
        if not diff:
            return "(no diff returned)"
        # Truncate to stay within reasonable prompt size
        if len(diff) > 6000:
            diff = diff[:6000] + "\n… (diff truncated)"
        return diff
    except Exception as e:
        return f"(diff fetch error: {e})"


# ── Event handlers ────────────────────────────────────────────────────────────

def handle_push(payload: dict):
    ref      = payload.get("ref", "refs/heads/unknown")
    branch   = ref.replace("refs/heads/", "")
    repo     = payload.get("repository", {}).get("full_name", GITHUB_REPO)
    pusher   = payload.get("pusher", {}).get("name", "unknown")
    commits  = len(payload.get("commits", []))

    log(f"push: {pusher} → {branch} ({commits} commit(s))")

    verify_script = PROJ_ROOT / "verify.sh"
    if verify_script.exists():
        try:
            r = subprocess.run(
                ["bash", str(verify_script)],
                capture_output=True, text=True, timeout=120, cwd=PROJ_ROOT,
            )
            if r.returncode == 0:
                health = "✅ Health check passed"
            else:
                tail = (r.stdout + r.stderr).strip()[-600:]
                health = f"❌ Health check failed\n<pre>{tail}</pre>"
        except subprocess.TimeoutExpired:
            health = "⏱ Health check timed out (120s)"
        except Exception as e:
            health = f"❌ Health check error: {e}"
    else:
        health = "⚠️ No verify.sh found"

    telegram_send(
        f"📦 <b>Push → {branch}</b>\n"
        f"By: {pusher} · {commits} commit{'s' if commits != 1 else ''}\n"
        f"Repo: <code>{repo}</code>\n\n"
        f"{health}"
    )


def handle_pull_request(payload: dict):
    action = payload.get("action", "")
    if action not in ("opened", "synchronize", "reopened"):
        log(f"pull_request action '{action}' — skipping")
        return

    pr        = payload.get("pull_request", {})
    pr_number = pr.get("number")
    pr_title  = pr.get("title", "")
    pr_author = pr.get("user", {}).get("login", "unknown")
    repo      = payload.get("repository", {}).get("full_name", GITHUB_REPO)

    log(f"pull_request #{pr_number} {action}: '{pr_title}' by {pr_author}")

    diff = fetch_pr_diff(repo, pr_number)

    prompt = (
        f"Review this pull request for Uncle J's Refinery.\n\n"
        f"PR #{pr_number}: {pr_title}\n"
        f"Author: {pr_author}\n\n"
        f"Diff:\n```diff\n{diff}\n```\n\n"
        f"Check for:\n"
        f"- New feature installers: do they have --uninstall, are they idempotent, "
        f"do they read from .env, do they use lib/notify.sh for Telegram?\n"
        f"- New skills: correct frontmatter (name, description, type)?\n"
        f"- Security: hardcoded secrets, missing validation, dangerous shell patterns?\n"
        f"- Anything broken or inconsistent with the existing codebase patterns?\n\n"
        f"Be concise. Bullet points. No preamble. If everything looks good, say so in one line."
    )

    review = run_claude(prompt)
    log(f"PR #{pr_number} review complete ({len(review)} chars)")

    comment_body = f"🤖 **Auto-review** (Uncle J's Refinery webhook)\n\n{review}"
    github_comment(repo, pr_number, comment_body)
    telegram_send(f"🔍 PR #{pr_number} reviewed → GitHub comment posted.")


# ── HTTP handler ──────────────────────────────────────────────────────────────

class WebhookHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # suppress default per-request stderr noise

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, b"OK")
        else:
            self._respond(404, b"Not found")

    def do_POST(self):
        if self.path != "/webhook":
            self._respond(404, b"Not found")
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        sig   = self.headers.get("X-Hub-Signature-256", "")
        event = self.headers.get("X-GitHub-Event", "")

        if not verify_signature(body, sig):
            err("Signature verification failed — request rejected")
            self._respond(403, b"Forbidden")
            return

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._respond(400, b"Bad JSON")
            return

        # Respond immediately so GitHub doesn't time out
        self._respond(200, b"OK")

        threading.Thread(target=self._dispatch, args=(event, payload), daemon=True).start()

    def _dispatch(self, event: str, payload: dict):
        log(f"dispatching: {event}")
        try:
            if event == "push":
                handle_push(payload)
            elif event == "pull_request":
                handle_pull_request(payload)
            elif event == "ping":
                log("ping received — webhook registered successfully")
                telegram_send("🔗 GitHub webhook connected to Uncle J's Refinery.")
            else:
                log(f"unhandled event: {event}")
        except Exception as e:
            err(f"dispatch error ({event}): {e}")

    def _respond(self, code: int, body: bytes):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log(f"Uncle J's Refinery — GitHub Webhook Server")
    log(f"  Port:   {WEBHOOK_PORT}")
    log(f"  Repo:   {GITHUB_REPO or '(not set — set GITHUB_REPO in .env)'}")
    log(f"  Secret: {'configured' if WEBHOOK_SECRET else 'NOT SET — set GITHUB_WEBHOOK_SECRET'}")
    log(f"  Claude: {CLAUDE_BIN}")

    server = http.server.ThreadingHTTPServer(("0.0.0.0", WEBHOOK_PORT), WebhookHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Shutting down.")

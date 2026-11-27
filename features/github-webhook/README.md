# GitHub Webhook Feature

GitHub sends a webhook, an automatic message over HTTP, when something happens in your repo. This server stays running so it can receive the message and act on it.

| Event | Action |
|---|---|
| `push` to any branch | Runs `verify.sh` (health check), sends result to Telegram |
| `pull_request` opened/updated | Fetches the code changes, asks Claude to review them, and posts the review as a GitHub comment |
| `ping` | Confirms webhook is connected, sends Telegram notification |

## Prerequisites

1. **A public URL** pointing at this machine — one of:
   - **ngrok**: `ngrok http 9000` → use the `https://….ngrok-free.app` URL
   - **Tailscale Funnel**: `tailscale funnel 9000` → use the `https://hostname.tail….ts.net` URL
   - **VPS / static IP**: configure your reverse proxy (nginx/caddy) to forward to port 9000

2. **GitHub CLI** authenticated: `gh auth login`

3. **Telegram credentials** already configured (from `features/stack-alerts/install.sh`)

4. The machine running the server must be **always on** for webhooks to be received reliably.

## Install

```bash
bash features/github-webhook/install.sh
```

The installer will:
1. Check dependencies (python3, curl, gh)
2. Prompt for your public URL, port (default 9000), and GitHub repo
3. Generate a webhook secret (or reuse an existing one from `.env`)
4. Write config to `.env`
5. Install and start a **systemd user service** (`uncle-j-webhook`), which runs the server in the background
6. Register the webhook on GitHub automatically via `gh api`
7. Send a Telegram confirmation

## Uninstall

```bash
bash features/github-webhook/install.sh --uninstall
```

This stops and removes the systemd service and deletes the webhook from GitHub.

## Status & logs

```bash
# Service status
bash features/github-webhook/install.sh --status

# Live logs
journalctl --user -u uncle-j-webhook -f

# Log file
tail -f state/github-webhook.log
```

## Manual test (after install)

Send a test message with a valid HMAC signature. The signature uses a shared secret so the server can check that the message came from someone who knows it.

```bash
SECRET=$(grep GITHUB_WEBHOOK_SECRET .env | cut -d= -f2)
PAYLOAD='{"zen":"test","hook_id":1,"hook":{"id":1}}'
SIG=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print "sha256="$2}')
curl -X POST http://localhost:9000/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: ping" \
  -H "X-Hub-Signature-256: $SIG" \
  -d "$PAYLOAD"
```

Look for an `OK` response, `ping received` in the logs, and a message in Telegram.

## Config (.env keys)

| Key | Description |
|---|---|
| `GITHUB_WEBHOOK_SECRET` | HMAC secret shared with GitHub — auto-generated on first install |
| `GITHUB_WEBHOOK_PORT` | Port the server listens on (default: `9000`) |
| `GITHUB_REPO` | `owner/repo` the webhook is registered on |
| `WEBHOOK_PUBLIC_URL` | Your public URL (ngrok/Tailscale/VPS) |

## Architecture

`scripts/github-webhook-server.py` uses only Python's standard library. `ThreadingHTTPServer` lets it handle several requests at once. Each event's work runs in its own background thread, so the server always replies before GitHub's 10-second timeout.

The server fetches the full set of code changes with `gh pr diff` before asking Claude for a pull request review. This gives Claude the changed code itself, not just the pull request's details. It borrows Hermes Agent's "script pre-injection" pattern: a script gathers the context before the model is called.

For every request, the server uses `GITHUB_WEBHOOK_SECRET` to compute an HMAC-SHA256 signature and checks it against `X-Hub-Signature-256`. It returns HTTP 403 if the signature is missing or wrong.

## Extending

Add new event handlers in `scripts/github-webhook-server.py`:

```python
def handle_issues(payload: dict):
    action = payload.get("action", "")
    if action != "opened":
        return
    # ... your logic here

# In WebhookHandler._dispatch:
elif event == "issues":
    handle_issues(payload)
```

Register the new event type when installing the webhook (or update it via `gh api`):

```bash
gh api repos/OWNER/REPO/hooks/HOOK_ID \
  --method PATCH \
  --field "events[]=push" \
  --field "events[]=pull_request" \
  --field "events[]=issues"
```

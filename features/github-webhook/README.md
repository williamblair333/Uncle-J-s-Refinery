# GitHub Webhook Feature

Runs a persistent HTTP server that receives GitHub events and acts on them automatically:

| Event | Action |
|---|---|
| `push` to any branch | Runs `verify.sh` (health check), sends result to Telegram |
| `pull_request` opened/updated | Fetches the diff, runs Claude auto-review, posts result as a GitHub comment |
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
5. Install and start a **systemd user service** (`uncle-j-webhook`)
6. Register the webhook on GitHub automatically via `gh api`
7. Send a Telegram confirmation

## Uninstall

```bash
bash features/github-webhook/install.sh --uninstall
```

Stops and removes the systemd service, deletes the webhook from GitHub.

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

Send a test payload with correct HMAC signature:

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

Expected: `OK` response, `ping received` in logs, Telegram message delivered.

## Config (.env keys)

| Key | Description |
|---|---|
| `GITHUB_WEBHOOK_SECRET` | HMAC secret shared with GitHub — auto-generated on first install |
| `GITHUB_WEBHOOK_PORT` | Port the server listens on (default: `9000`) |
| `GITHUB_REPO` | `owner/repo` the webhook is registered on |
| `WEBHOOK_PUBLIC_URL` | Your public URL (ngrok/Tailscale/VPS) |

## Architecture

The server is `scripts/github-webhook-server.py` — pure Python stdlib, no pip dependencies. It uses `ThreadingHTTPServer` so concurrent events don't block each other. Each event is dispatched to a background thread so GitHub's 10-second delivery timeout is never hit.

**PR review pre-injection**: before calling Claude, the server fetches the full diff with `gh pr diff`. Claude sees the actual changed code, not just metadata — the same "script pre-injection" pattern from Hermes Agent applied to webhook context.

**Signature verification**: every request is verified against `GITHUB_WEBHOOK_SECRET` using HMAC-SHA256 (`X-Hub-Signature-256`). Requests with missing or incorrect signatures are rejected with HTTP 403.

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

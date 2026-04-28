#!/usr/bin/env bash
# Install/uninstall the Uncle J's Refinery GitHub webhook server.
#
# Usage:
#   bash features/github-webhook/install.sh            # install
#   bash features/github-webhook/install.sh --uninstall
#   bash features/github-webhook/install.sh --status

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJ_ROOT/.env"
SERVER_SCRIPT="$PROJ_ROOT/scripts/github-webhook-server.py"
SERVICE_NAME="uncle-j-webhook"
SERVICE_FILE="$HOME/.config/systemd/user/${SERVICE_NAME}.service"

source "$PROJ_ROOT/lib/feature-helpers.sh"

step()  { printf '\n==> %s\n' "$*"; }
ok()    { printf '    OK  %s\n' "$*"; }
warn()  { printf '    !!  %s\n' "$*" >&2; }

# ── Status ────────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--status" ]]; then
  systemctl --user status "$SERVICE_NAME" 2>/dev/null || echo "Service not installed."
  exit 0
fi

# ── Uninstall ─────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
  step "Uninstalling GitHub webhook server"

  systemctl --user stop    "$SERVICE_NAME" 2>/dev/null && ok "Service stopped"    || true
  systemctl --user disable "$SERVICE_NAME" 2>/dev/null && ok "Service disabled"   || true
  rm -f "$SERVICE_FILE" && ok "Unit file removed" || true
  systemctl --user daemon-reload 2>/dev/null || true

  # Remove webhook from GitHub if we have the hook ID stored
  HOOK_ID_FILE="$PROJ_ROOT/state/github-webhook-hook-id.txt"
  if [[ -f "$HOOK_ID_FILE" ]] && [[ -f "$ENV_FILE" ]]; then
    set -a; source "$ENV_FILE"; set +a
    HOOK_ID=$(cat "$HOOK_ID_FILE")
    if [[ -n "${GITHUB_REPO:-}" && -n "$HOOK_ID" ]]; then
      gh api "repos/${GITHUB_REPO}/hooks/${HOOK_ID}" --method DELETE 2>/dev/null \
        && ok "GitHub webhook #${HOOK_ID} deleted" || warn "Could not delete GitHub webhook (may already be gone)"
      rm -f "$HOOK_ID_FILE"
    fi
  fi

  echo ""
  echo "  Secrets left in $ENV_FILE: GITHUB_WEBHOOK_SECRET, GITHUB_WEBHOOK_PORT, GITHUB_REPO"
  echo "  Remove manually if desired."
  exit 0
fi

# ── Dependency check ──────────────────────────────────────────────────────────
step "Checking dependencies"

for cmd in python3 curl; do
  command -v "$cmd" &>/dev/null && ok "$cmd" || { warn "$cmd not found"; exit 1; }
done

# gh CLI — needed to register webhook and post review comments
if ! command -v gh &>/dev/null; then
  warn "gh (GitHub CLI) not found. Install from https://cli.github.com then re-run."
  exit 1
fi
ok "gh"

# Confirm gh is authenticated
if ! gh auth status &>/dev/null; then
  warn "gh is not authenticated. Run: gh auth login"
  exit 1
fi
ok "gh authenticated"

# systemd user session
if ! systemctl --user status &>/dev/null; then
  warn "systemd user session not available. Start one with: loginctl enable-linger \$USER"
  exit 1
fi
ok "systemd user session"

[[ -f "$SERVER_SCRIPT" ]] || { warn "Missing $SERVER_SCRIPT"; exit 1; }
ok "webhook server script present"

# ── Configuration prompts ─────────────────────────────────────────────────────
step "Configuration"
echo ""

# Load existing values as defaults
[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a || true

# Public URL (ngrok/Tailscale Funnel/VPS)
echo "  This is the public URL GitHub will POST to."
echo "  Examples:"
echo "    ngrok:           https://abc123.ngrok-free.app"
echo "    Tailscale Funnel: https://hostname.tail1234.ts.net"
echo "    VPS:             https://myserver.example.com"
echo ""
prompt_value "Your public URL (no trailing slash)" "${WEBHOOK_PUBLIC_URL:-}" WEBHOOK_PUBLIC_URL
[[ -z "$WEBHOOK_PUBLIC_URL" ]] && { warn "Public URL required."; exit 1; }
# Strip trailing slash
WEBHOOK_PUBLIC_URL="${WEBHOOK_PUBLIC_URL%/}"

prompt_value "Port to listen on" "${GITHUB_WEBHOOK_PORT:-9000}" GITHUB_WEBHOOK_PORT

# GitHub repo
DEFAULT_REPO=$(git -C "$PROJ_ROOT" remote get-url origin 2>/dev/null \
  | sed 's|.*github.com[:/]\(.*\)\.git|\1|;s|.*github.com[:/]\(.*\)|\1|' || echo "")
prompt_value "GitHub repo (owner/name)" "${GITHUB_REPO:-$DEFAULT_REPO}" GITHUB_REPO
[[ -z "$GITHUB_REPO" ]] && { warn "Repo required."; exit 1; }

# Webhook secret — generate one if not provided
EXISTING_SECRET="${GITHUB_WEBHOOK_SECRET:-}"
if [[ -z "$EXISTING_SECRET" ]]; then
  GENERATED=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  prompt_value "Webhook secret (leave blank to generate)" "" INPUT_SECRET
  GITHUB_WEBHOOK_SECRET="${INPUT_SECRET:-$GENERATED}"
else
  echo "  Existing webhook secret found — keeping it."
  GITHUB_WEBHOOK_SECRET="$EXISTING_SECRET"
fi

# ── Write config ──────────────────────────────────────────────────────────────
step "Writing config to $ENV_FILE"
write_env_var "$ENV_FILE" "GITHUB_WEBHOOK_SECRET" "$GITHUB_WEBHOOK_SECRET"
write_env_var "$ENV_FILE" "GITHUB_WEBHOOK_PORT"   "$GITHUB_WEBHOOK_PORT"
write_env_var "$ENV_FILE" "GITHUB_REPO"           "$GITHUB_REPO"
write_env_var "$ENV_FILE" "WEBHOOK_PUBLIC_URL"    "$WEBHOOK_PUBLIC_URL"
ok ".env updated"

# ── Install systemd service ───────────────────────────────────────────────────
step "Installing systemd user service"

mkdir -p "$(dirname "$SERVICE_FILE")"
PYTHON_BIN=$(command -v python3)

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Uncle J's Refinery GitHub Webhook Server
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROJ_ROOT}
ExecStart=${PYTHON_BIN} ${SERVER_SCRIPT}
Restart=always
RestartSec=5
StandardOutput=append:${PROJ_ROOT}/state/github-webhook.log
StandardError=append:${PROJ_ROOT}/state/github-webhook.log

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"
systemctl --user restart "$SERVICE_NAME"

# Give it a moment to start
sleep 2

if systemctl --user is-active --quiet "$SERVICE_NAME"; then
  ok "Service running"
else
  warn "Service failed to start — check: journalctl --user -u $SERVICE_NAME"
  exit 1
fi

# ── Smoke test: local health endpoint ─────────────────────────────────────────
step "Smoke testing local /health endpoint"
HEALTH=$(curl -sf "http://localhost:${GITHUB_WEBHOOK_PORT}/health" 2>/dev/null || echo "FAIL")
if [[ "$HEALTH" == "OK" ]]; then
  ok "/health returned OK"
else
  warn "/health check failed — server may not have started yet"
  warn "Check: journalctl --user -u $SERVICE_NAME"
  exit 1
fi

# ── Register webhook with GitHub ──────────────────────────────────────────────
step "Registering webhook with GitHub (repo: $GITHUB_REPO)"

WEBHOOK_URL="${WEBHOOK_PUBLIC_URL}/webhook"

# Remove any existing uncle-j webhook to avoid duplicates
EXISTING_HOOKS=$(gh api "repos/${GITHUB_REPO}/hooks" 2>/dev/null || echo "[]")
EXISTING_ID=$(python3 -c "
import sys, json
hooks = json.loads(sys.argv[1])
for h in hooks:
    if 'uncle-j' in h.get('config', {}).get('url', '') or \
       sys.argv[2] in h.get('config', {}).get('url', ''):
        print(h['id'])
        break
" "$EXISTING_HOOKS" "$WEBHOOK_PUBLIC_URL" 2>/dev/null || echo "")

if [[ -n "$EXISTING_ID" ]]; then
  gh api "repos/${GITHUB_REPO}/hooks/${EXISTING_ID}" --method DELETE &>/dev/null || true
  ok "Removed existing webhook #${EXISTING_ID}"
fi

HOOK_RESPONSE=$(gh api "repos/${GITHUB_REPO}/hooks" \
  --method POST \
  --field "name=web" \
  --field "active=true" \
  --field "events[]=push" \
  --field "events[]=pull_request" \
  --field "config[url]=${WEBHOOK_URL}" \
  --field "config[content_type]=json" \
  --field "config[secret]=${GITHUB_WEBHOOK_SECRET}" \
  --field "config[insecure_ssl]=0" 2>&1)

HOOK_ID=$(echo "$HOOK_RESPONSE" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('id', ''))
except:
    pass
" 2>/dev/null || echo "")

if [[ -n "$HOOK_ID" ]]; then
  echo "$HOOK_ID" > "$PROJ_ROOT/state/github-webhook-hook-id.txt"
  ok "Webhook #${HOOK_ID} registered → ${WEBHOOK_URL}"
else
  warn "GitHub webhook registration may have failed."
  warn "Response: $HOOK_RESPONSE"
  warn "Register manually at: https://github.com/${GITHUB_REPO}/settings/hooks"
fi

# ── Telegram confirmation ─────────────────────────────────────────────────────
if [[ -f "$ENV_FILE" ]]; then
  set -a; source "$ENV_FILE"; set +a
fi
if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  source "$PROJ_ROOT/lib/notify.sh"
  notify_send_text "🔗 <b>GitHub webhook active</b>

Repo: <code>${GITHUB_REPO}</code>
Endpoint: <code>${WEBHOOK_URL}</code>
Port: <code>${GITHUB_WEBHOOK_PORT}</code>

Events: push → health check, pull_request → auto-review" || true
fi

# ── Summary ───────────────────────────────────────────────────────────────────
step "Done"
echo ""
echo "  Service:   systemctl --user status $SERVICE_NAME"
echo "  Logs:      $PROJ_ROOT/state/github-webhook.log"
echo "  Endpoint:  ${WEBHOOK_URL}"
echo "  Health:    http://localhost:${GITHUB_WEBHOOK_PORT}/health"
echo ""
echo "  Events handled:"
echo "    push          → runs verify.sh, notifies Telegram"
echo "    pull_request  → fetches diff, auto-reviews with Claude, posts GitHub comment"
echo ""
echo "  To uninstall:  bash $SCRIPT_DIR/install.sh --uninstall"
echo "  To check:      bash $SCRIPT_DIR/install.sh --status"

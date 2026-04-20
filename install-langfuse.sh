#!/usr/bin/env bash
# install-langfuse.sh — spins up a self-hosted Langfuse on Linux/macOS
# and wires the Stop hook that ships every Claude Code turn to it.
#
# What this script does:
#   1. Verifies Docker is installed and the daemon is reachable.
#   2. Clones doneyli/claude-code-langfuse-template if missing.
#   3. Generates .env with random secure credentials.
#   4. docker compose up -d  (pulls ~5 GB of images on first run).
#   5. Waits for Langfuse web to be ready.
#   6. Runs the upstream scripts/install-hook.sh.
#   7. Pins langfuse Python SDK to v3 (the hook uses v3 API).
#   8. Patches ~/.claude/settings.json to register the Stop hook and
#      set LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY /
#      TRACE_TO_LANGFUSE=true in the env block.

set -euo pipefail
STACK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$STACK_ROOT"

TEMPLATE_DIR="$STACK_ROOT/claude-code-langfuse-template"
LANGFUSE_URL="http://localhost:3050"
CLAUDE_DIR="${CLAUDE_HOME:-$HOME/.claude}"

step() { printf '\n==> %s\n'  "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }
has()  { command -v "$1" >/dev/null 2>&1; }

# ── 1. Docker ────────────────────────────────────────────────────────────
step "Checking Docker"
if ! has docker; then
    warn "Docker not installed. Installing via the official convenience script."
    warn "This installs Docker CE and adds you to the docker group."
    read -r -p "    Proceed with Docker install? [y/N] " ans
    if [[ ! "$ans" =~ ^[Yy]$ ]]; then
        echo "Aborted. Install Docker manually, then re-run."; exit 1
    fi
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER" || true
    warn "You must log out and back in (or run 'newgrp docker') for group membership to take effect."
    warn "After that, re-run this script."
    exit 0
fi

if ! docker info >/dev/null 2>&1; then
    warn "docker binary present but daemon not reachable."
    warn "Start it:    sudo systemctl start docker"
    warn "Fix perms:   sudo usermod -aG docker \$USER && newgrp docker"
    exit 1
fi
ok "docker $(docker --version | awk '{print $3}' | tr -d ,)"

if ! docker compose version >/dev/null 2>&1; then
    warn "docker compose plugin missing. Install it:"
    warn "  Debian/Ubuntu: sudo apt install docker-compose-plugin"
    warn "  Fedora/RHEL:   sudo dnf install docker-compose-plugin"
    warn "  Arch:          sudo pacman -S docker-compose"
    exit 1
fi

# ── 2. Clone template ────────────────────────────────────────────────────
if [ ! -d "$TEMPLATE_DIR" ]; then
    step "Cloning doneyli/claude-code-langfuse-template"
    if ! has git; then
        warn "git not found; run ./prerequisites.sh first"
        exit 1
    fi
    git clone --depth 1 https://github.com/doneyli/claude-code-langfuse-template.git "$TEMPLATE_DIR"
fi
ok "template present at $TEMPLATE_DIR"

# ── 3. Generate .env ─────────────────────────────────────────────────────
cd "$TEMPLATE_DIR"
if [ ! -f ".env" ] || ! grep -q LANGFUSE_INIT_PROJECT_SECRET_KEY .env 2>/dev/null; then
    step "Generating .env with random credentials"
    if [ -x "./scripts/generate-env.sh" ]; then
        ./scripts/generate-env.sh
    else
        warn "generate-env.sh not found or not executable"
        exit 1
    fi
fi
ok ".env present"

# ── 4. docker compose up ─────────────────────────────────────────────────
step "Starting Langfuse stack (docker compose up -d)"
docker compose up -d

# ── 5. Wait for Langfuse web ─────────────────────────────────────────────
step "Waiting for Langfuse web to become ready"
for i in $(seq 1 120); do
    if curl -fsS -o /dev/null "$LANGFUSE_URL/api/public/health" 2>/dev/null; then
        ok "Langfuse web is ready (after ${i}s)"
        break
    fi
    sleep 1
    if [ "$i" -eq 120 ]; then
        warn "Timed out waiting for Langfuse. Check 'docker compose logs langfuse-web'."
        exit 1
    fi
done

# ── 6. Install the Python hook script ────────────────────────────────────
step "Running upstream install-hook.sh"
if [ -x "./scripts/install-hook.sh" ]; then
    ./scripts/install-hook.sh || warn "install-hook.sh exited non-zero (we'll patch settings.json manually next)"
fi
ok "hook script installed to $CLAUDE_DIR/hooks/langfuse_hook.py"

# ── 7. Pin langfuse SDK to v3 (the hook API target) ──────────────────────
step "Pinning langfuse SDK to v3"
PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
    warn "No python/python3 on PATH; skipping SDK pin. Install manually:"
    warn "  python3 -m pip install --upgrade 'langfuse>=3.0,<4'"
else
    "$PY" -m pip install --quiet --upgrade "langfuse>=3.0,<4" || \
        "$PY" -m pip install --user --quiet --upgrade "langfuse>=3.0,<4"
    ok "langfuse pinned to v3.x"
fi

# ── 8. Patch settings.json ───────────────────────────────────────────────
step "Patching ~/.claude/settings.json with Stop hook and Langfuse env vars"
mkdir -p "$CLAUDE_DIR/state"

"$PY" - <<PY
import json, shutil, os
from pathlib import Path

settings_path = Path(os.path.expanduser("${CLAUDE_DIR}")) / "settings.json"
hook_path     = Path(os.path.expanduser("${CLAUDE_DIR}")) / "hooks" / "langfuse_hook.py"
env_path      = Path(r"${TEMPLATE_DIR}") / ".env"

# backup
if settings_path.exists():
    shutil.copy(str(settings_path), str(settings_path) + ".bak.langfuse")
else:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text("{}")

# parse .env
creds = {}
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        creds[k.strip()] = v.strip().strip('"').strip("'")

# merge settings
d = json.loads(settings_path.read_text())
python_cmd = os.environ.get("PYTHON_BIN") or "python3"
d.setdefault("hooks", {})["Stop"] = [{
    "matcher": "",
    "hooks": [{
        "type": "command",
        "command": f'{python_cmd} "{hook_path}"'
    }]
}]
d.setdefault("env", {}).update({
    "LANGFUSE_HOST":       "${LANGFUSE_URL}",
    "LANGFUSE_PUBLIC_KEY": creds.get("LANGFUSE_INIT_PROJECT_PUBLIC_KEY", ""),
    "LANGFUSE_SECRET_KEY": creds.get("LANGFUSE_INIT_PROJECT_SECRET_KEY", ""),
    "TRACE_TO_LANGFUSE":   "true",
    # PYTHONUTF8 is harmless on Linux (already UTF-8) but saves a lot of
    # pain for anyone copying this config to Windows.
    "PYTHONUTF8":          "1",
})
settings_path.write_text(json.dumps(d, indent=2))
print("  OK  settings.json patched")
print(f"      public key : {creds.get('LANGFUSE_INIT_PROJECT_PUBLIC_KEY', '<missing>')}")
print(f"      secret key : {creds.get('LANGFUSE_INIT_PROJECT_SECRET_KEY', '<missing>')[:10]}...")
print(f"      host       : ${LANGFUSE_URL}")
PY

step "Langfuse install complete"
cat <<EOF

Langfuse UI:  $LANGFUSE_URL
Login: admin@localhost.local
Password: see LANGFUSE_INIT_USER_PASSWORD in $TEMPLATE_DIR/.env

End-to-end smoke test:

  cd /tmp
  claude
  # inside the session: ask something, then /quit
  tail ~/.claude/state/langfuse_hook.log

You should see "[INFO] Processed N turns ... in X.Xs" and the trace
should appear in the Langfuse UI under the Claude Code project within
a few seconds.
EOF

#!/usr/bin/env bash
# One-shot installer for the Claude retrieval stack on Linux / macOS.
#
# Usage:
#   ./install.sh                 # install stack, print next-step guidance
#   ./install.sh --auto-register # also register servers with Claude Code CLI
#   ./install.sh --skip-optional # skip MotherDuck warm-cache
#
# Re-runs are idempotent.

set -euo pipefail
STACK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$STACK_ROOT"

AUTO_REGISTER=0
SKIP_OPTIONAL=0
for arg in "$@"; do
    case "$arg" in
        --auto-register) AUTO_REGISTER=1 ;;
        --skip-optional) SKIP_OPTIONAL=1 ;;
    esac
done

step()  { printf '\n==> %s\n'  "$*"; }
ok()    { printf '    OK  %s\n' "$*"; }
warn()  { printf '    !!  %s\n' "$*" >&2; }
has()   { command -v "$1" >/dev/null 2>&1; }

# --- 1. Prereqs --------------------------------------------------------------
step "Checking prerequisites"
if ! has python3; then
    echo "Python 3.11+ not found on PATH. Install it and re-run." >&2
    exit 1
fi
ok "python3 $(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

if ! has uv; then
    step "Installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck disable=SC1091
    export PATH="$HOME/.local/bin:$PATH"
    has uv || { echo "uv install succeeded but not on PATH. Open a new shell and re-run." >&2; exit 1; }
fi
ok "uv $(uv --version | awk '{print $2}')"

if has node; then
    ok "node $(node --version)"
    SKIP_CONTEXT7=0
else
    warn "Node.js not found. Context7 will be skipped. Install Node 18+ to enable it."
    SKIP_CONTEXT7=1
fi

if has claude; then
    ok "claude CLI found"
    SKIP_CLAUDE_CLI=0
else
    warn "Claude Code CLI not found. Auto-registration (if requested) will be skipped."
    SKIP_CLAUDE_CLI=1
fi

# --- 2. Create venv and install Python stack --------------------------------
step "Creating .venv with uv"
[ -d .venv ] || uv venv --python 3.11
ok ".venv ready at $STACK_ROOT/.venv"

step "Installing Python stack (jCodeMunch, jDataMunch, jDocMunch, MemPalace)"
# --inexact: don't remove extraneous packages (e.g. langfuse installed by
# install-langfuse.sh). Without this, re-running install.sh after
# install-langfuse.sh silently deletes the Langfuse SDK and breaks the
# Stop hook.
uv sync --inexact
ok "Python stack installed"

VENV_BIN="$STACK_ROOT/.venv/bin"
declare -A EXE=(
    [jcodemunch]="$VENV_BIN/jcodemunch-mcp"
    [jdatamunch]="$VENV_BIN/jdatamunch-mcp"
    [jdocmunch]="$VENV_BIN/jdocmunch-mcp"
    [mempalace]="$VENV_BIN/mempalace"
)
for k in "${!EXE[@]}"; do
    if [ -x "${EXE[$k]}" ]; then ok "$k -> ${EXE[$k]}"
    else warn "$k missing at ${EXE[$k]}"
    fi
done

# --- 3. Warm-cache Serena and MotherDuck via uvx ----------------------------
step "Warm-caching Serena"
if uvx --from git+https://github.com/oraios/serena serena --help >/dev/null 2>&1; then
    ok "Serena cached"
else
    warn "Serena warm-cache failed (non-fatal; uvx will retry when invoked)."
fi

if [ "$SKIP_OPTIONAL" -eq 0 ]; then
    step "Warm-caching mcp-server-motherduck"
    if uvx mcp-server-motherduck --help >/dev/null 2>&1; then
        ok "mcp-server-motherduck cached"
    else
        warn "mcp-server-motherduck warm-cache failed (non-fatal)."
    fi
fi

# --- 3b. Configure Serena: disable dashboard browser auto-open --------------
# Serena's default is to open a new browser tab every time its MCP server
# starts -- that's once per Claude Code session. With multiple sessions or
# orphaned Serena processes, the tabs pile up. The dashboard is still
# reachable at http://localhost:24282/dashboard/ (port increments if
# multiple Serena instances are running).
step "Configuring Serena: disable dashboard browser auto-open"
SERENA_CFG="$HOME/.serena/serena_config.yml"
mkdir -p "$(dirname "$SERENA_CFG")"

# Nudge Serena to write its default config if it hasn't yet. `--help`
# exits before config load, so we briefly start the MCP server (stdin
# closed so it exits fast) and let timeout reap it.
if [ ! -f "$SERENA_CFG" ]; then
    timeout 8 uvx --from git+https://github.com/oraios/serena \
        serena start-mcp-server --context ide-assistant \
        </dev/null >/dev/null 2>&1 || true
fi

if [ -f "$SERENA_CFG" ]; then
    if grep -qE '^[[:space:]]*web_dashboard_open_on_launch:' "$SERENA_CFG"; then
        sed -i.bak -E 's/^([[:space:]]*web_dashboard_open_on_launch:).*/\1 false/' "$SERENA_CFG"
        rm -f "$SERENA_CFG.bak"
    else
        printf '\nweb_dashboard_open_on_launch: false\n' >> "$SERENA_CFG"
    fi
    ok "Serena dashboard auto-open disabled"
else
    cat > "$SERENA_CFG" <<'YML'
# Managed by Uncle J's Refinery install.sh.
# Prevents Serena from auto-opening a browser tab on each MCP session
# start. Dashboard still reachable at http://localhost:24282/dashboard/
# (port increments if multiple Serena instances run concurrently).
web_dashboard_open_on_launch: false
YML
    ok "Serena config stub written"
fi

# --- 4. jcodemunch init (hooks + audit) -------------------------------------
step "Running jcodemunch-mcp init --yes --hooks --audit"
if [ -x "${EXE[jcodemunch]}" ]; then
    "${EXE[jcodemunch]}" init --yes --hooks --audit 2>&1 | tee "$STACK_ROOT/.install-jcm-init.log" || \
        warn "jcodemunch init returned non-zero (see .install-jcm-init.log)"
fi

# --- 4b. Patch hook commands to use the full venv-binary path ---------------
# `jcodemunch-mcp init --hooks` writes bare `jcodemunch-mcp <subcommand>`
# into ~/.claude/settings.json. Those only resolve if the venv is on PATH,
# which it usually isn't — so every Claude Code tool call prints
# "command not found" for the enforcement hooks. Rewrite to the full
# path so hooks actually fire.
if [ -f "$STACK_ROOT/patch-jcodemunch-hook-paths.py" ]; then
    step "Patching jcodemunch-mcp hook commands to use full binary path"
    if "$VENV_BIN/python" "$STACK_ROOT/patch-jcodemunch-hook-paths.py"; then
        ok "hook paths patched"
    else
        warn "hook path patch failed; hooks will print 'command not found' at runtime"
        warn "Re-run manually:  $VENV_BIN/python $STACK_ROOT/patch-jcodemunch-hook-paths.py"
    fi
else
    warn "patch-jcodemunch-hook-paths.py missing from stack root; hook commands may fail with 'command not found'."
fi

# --- 4c. Render mcp-clients/*.json from *.json.tmpl -------------------------
# The committed templates use {{STACK_VENV_BIN}} and {{EXE}} placeholders.
# Install-time rendering produces .json files (gitignored) that users can
# paste into their MCP client configs.
step "Rendering mcp-clients/*.json from templates"
MCP_DIR="$STACK_ROOT/mcp-clients"
if ls "$MCP_DIR"/*.json.tmpl >/dev/null 2>&1; then
    for tmpl in "$MCP_DIR"/*.json.tmpl; do
        out="${tmpl%.tmpl}"
        sed -e "s|{{STACK_VENV_BIN}}|$VENV_BIN|g" -e "s|{{EXE}}||g" "$tmpl" > "$out"
        ok "rendered $(basename "$out")"
    done
else
    warn "no *.json.tmpl files in $MCP_DIR; skipping render"
fi

# --- 5. Optional auto-registration with Claude Code -------------------------
# Note: `claude mcp add -s user <name>` silently skips when the name is
# already registered. `jcodemunch-mcp init` registers itself as
# `uvx jcodemunch-mcp` at *local* scope, which wins over user scope —
# so we must clear all three scopes before re-adding at user scope.
# Otherwise the uvx version keeps overriding the venv-pinned binary.
mcp_add() {
    local name="$1"; shift
    claude mcp remove -s local   "$name" >/dev/null 2>&1 || true
    claude mcp remove -s project "$name" >/dev/null 2>&1 || true
    claude mcp remove -s user    "$name" >/dev/null 2>&1 || true
    claude mcp add -s user "$name" "$@"
}
if [ "$AUTO_REGISTER" -eq 1 ] && [ "$SKIP_CLAUDE_CLI" -eq 0 ]; then
    step "Registering MCP servers with Claude Code (user scope)"
    mcp_add jcodemunch "${EXE[jcodemunch]}"
    mcp_add jdatamunch "${EXE[jdatamunch]}"
    mcp_add jdocmunch  "${EXE[jdocmunch]}"
    mcp_add mempalace -- "$VENV_BIN/python" -m mempalace.mcp_server
    mcp_add serena -- uvx --from git+https://github.com/oraios/serena serena start-mcp-server --context ide-assistant
    [ "$SKIP_CONTEXT7" -eq 0 ] && mcp_add context7 -- npx -y "@upstash/context7-mcp"
    [ "$SKIP_OPTIONAL" -eq 0 ] && mcp_add duckdb -- uvx mcp-server-motherduck --db-path :memory: --read-write --allow-switch-databases
    ok "Registered. Verify with: claude mcp list"
fi

# --- 5b. MCP server startup timeout ----------------------------------------
# Claude Code honors MCP_TIMEOUT from its settings.json env block. Set it
# here so first-run cold starts (uvx fetches, npx resolves) don't race the
# default 30s timeout — especially relevant for Serena and MotherDuck which
# can take 40-50s on their first invocation.
step "Setting MCP_TIMEOUT in ~/.claude/settings.json"
CLAUDE_DIR="${CLAUDE_HOME:-$HOME/.claude}"
mkdir -p "$CLAUDE_DIR"
[ -f "$CLAUDE_DIR/settings.json" ] || echo '{}' > "$CLAUDE_DIR/settings.json"
python3 - <<'PY'
import json, os
from pathlib import Path
p = Path(os.path.expanduser(os.environ.get("CLAUDE_HOME") or "~/.claude")) / "settings.json"
d = json.loads(p.read_text())
env = d.setdefault("env", {})
if env.get("MCP_TIMEOUT") != "60000":
    env["MCP_TIMEOUT"] = "60000"
    p.write_text(json.dumps(d, indent=2))
    print("    OK  MCP_TIMEOUT=60000 set in settings.json env block")
else:
    print("    OK  MCP_TIMEOUT already 60000 in settings.json env block")
PY

# --- 6. Next-step guidance --------------------------------------------------
step "Next steps"
cat <<EOF

Installed. What to do now:

1. Paste the MCP config fragment into your client:
     Claude Desktop  -> mcp-clients/claude-desktop-config-fragment.json
     Claude Code     -> mcp-clients/claude-code-mcp.json  (or re-run with --auto-register)
     Cursor          -> mcp-clients/cursor-mcp.json
     Windsurf        -> mcp-clients/windsurf-mcp.json

2. Install CLAUDE.md (routing policy) globally OR per-project:
     Global : cp CLAUDE.md ~/.claude/CLAUDE.md
     Project: cp CLAUDE.md /path/to/repo/CLAUDE.md

3. Bootstrap MemPalace for a project (one-time per project):
     $VENV_BIN/mempalace init ~/path/to/project
     $VENV_BIN/mempalace mine ~/path/to/project
     $VENV_BIN/mempalace mine ~/.claude/projects/ --mode convos

4. Sanity-check:
     ./verify.sh

5. Get free Context7 API key (optional, higher rate limits):
     https://context7.com/dashboard  -> put CONTEXT7_API_KEY=... in ~/.claude/.env

EOF

# --- 7. Optional features ----------------------------------------------------
step "Optional features"
source "$STACK_ROOT/lib/feature-helpers.sh"
echo ""
if prompt_yes_no "Enable automated stack update alerts (Telegram)?"; then
  bash "$STACK_ROOT/features/stack-alerts/install.sh"
fi

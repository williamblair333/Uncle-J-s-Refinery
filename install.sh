#!/usr/bin/env bash
# One-shot installer for the Claude retrieval stack on Linux / macOS.
# Mirrors install.ps1 for non-Windows environments.
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
uv sync
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
# The committed templates use {{STACK_VENV_BIN}} and {{EXE}} placeholders so
# the same files work on Linux and Windows. Install-time rendering produces
# platform-specific .json files (gitignored) that users can paste into
# their MCP client configs.
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
if [ "$AUTO_REGISTER" -eq 1 ] && [ "$SKIP_CLAUDE_CLI" -eq 0 ]; then
    step "Registering MCP servers with Claude Code (user scope)"
    claude mcp add -s user jcodemunch "${EXE[jcodemunch]}"
    claude mcp add -s user jdatamunch "${EXE[jdatamunch]}"
    claude mcp add -s user jdocmunch  "${EXE[jdocmunch]}"
    claude mcp add -s user mempalace -- "$VENV_BIN/python" -m mempalace.mcp_server
    claude mcp add -s user serena -- uvx --from git+https://github.com/oraios/serena serena start-mcp-server --context ide-assistant
    [ "$SKIP_CONTEXT7" -eq 0 ] && claude mcp add -s user context7 -- npx -y "@upstash/context7-mcp"
    [ "$SKIP_OPTIONAL" -eq 0 ] && claude mcp add -s user duckdb -- uvx mcp-server-motherduck --db-path :memory: --read-write --allow-switch-databases
    ok "Registered. Verify with: claude mcp list"
fi

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

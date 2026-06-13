#!/usr/bin/env bash
# One-shot installer for the Claude retrieval stack on Debian/Ubuntu Linux.
#
# Usage:
#   ./install.sh                    # install stack + register MCP servers + run healthcheck
#   ./install.sh --skip-optional    # skip MotherDuck warm-cache
#   ./install.sh --non-interactive  # skip all optional-feature prompts (CI/automation)
#
# MCP servers are always registered (--auto-register is now the default).
# After install, restart Claude Code then run: bash healthcheck.sh
#
# Re-runs are idempotent.

set -euo pipefail
STACK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$STACK_ROOT"

AUTO_REGISTER=1
SKIP_OPTIONAL=0
NON_INTERACTIVE=0
for arg in "$@"; do
    case "$arg" in
        --auto-register)   AUTO_REGISTER=1 ;;
        --skip-optional)   SKIP_OPTIONAL=1 ;;
        --non-interactive) NON_INTERACTIVE=1 ;;
    esac
done
export NON_INTERACTIVE

step()  { printf '\n==> %s\n'  "$*"; }
ok()    { printf '    OK  %s\n' "$*"; }
warn()  { printf '    !!  %s\n' "$*" >&2; }
has()   { command -v "$1" >/dev/null 2>&1; }

# Source early so install_cron / prompt_yes_no are available throughout
source "$STACK_ROOT/lib/feature-helpers.sh"

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

# --- 2b. Patch venv to use pysqlite3 (SQLite 3.51.3) instead of stdlib sqlite3 ---
# SQLite <3.51.3 has a WAL-reset data race bug present since 3.7.0 (2010).
# The uv-managed Python 3.11 has SQLite 3.50.4 statically compiled in.
# pysqlite3 bundles 3.51.3 (the fix). The .pth file applies the swap at every
# venv process startup — covers mine crons, repair script, and MCP server.
# Re-run after any `uv sync --reinstall` that wipes site-packages.
SITE_PKGS="$STACK_ROOT/.venv/lib/python3.11/site-packages"
step "Wiring pysqlite3 SQLite 3.51.3 patch into venv"
# Check the bundled SQLite version — the PyPI wheel has 3.51.1 (still affected).
# We need >= 3.51.3, so always build from source if the version check fails.
_psql_ver=$("$STACK_ROOT/.venv/bin/python3" -c "import pysqlite3; print(pysqlite3.sqlite_version)" 2>/dev/null || echo "0.0.0")
_need_build=$("$STACK_ROOT/.venv/bin/python3" -c "
v=tuple(int(x) for x in '$_psql_ver'.split('.'))
print('yes' if v < (3,51,3) else 'no')
" 2>/dev/null || echo "yes")
if [ "$_need_build" = "yes" ]; then
  # pysqlite3 missing or bundles SQLite < 3.51.3 — build from source against 3.51.3
  warn "pysqlite3 SQLite version '$_psql_ver' < 3.51.3 — building from source"
  SQLITE_AMALG_URL="https://www.sqlite.org/2026/sqlite-amalgamation-3510300.zip"
  TMP_SRC=$(mktemp -d)
  curl -sL "$SQLITE_AMALG_URL" -o "$TMP_SRC/amalg.zip"
  unzip -j "$TMP_SRC/amalg.zip" "*/sqlite3.c" "*/sqlite3.h" -d "$TMP_SRC/"
  uv pip download "pysqlite3==0.6.0" --no-binary :all: -d "$TMP_SRC" \
    --python "$STACK_ROOT/.venv/bin/python3" -q
  tar xz -C "$TMP_SRC" -f "$TMP_SRC"/pysqlite3-*.tar.gz
  cp "$TMP_SRC/sqlite3.c" "$TMP_SRC/sqlite3.h" "$TMP_SRC/pysqlite3-0.6.0/"
  uv pip install "$TMP_SRC/pysqlite3-0.6.0/" --python "$STACK_ROOT/.venv/bin/python3" --force-reinstall
  rm -rf "$TMP_SRC"
fi
cat > "$SITE_PKGS/_pysqlite3_patch.py" << 'PYEOF'
# WAL data-race fix: swap stdlib sqlite3 for pysqlite3 (SQLite 3.51.3+).
# Applies to every process in this venv at interpreter startup via .pth file.
try:
    __import__('pysqlite3')
    import sys
    sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
except ImportError:
    pass  # graceful fallback if pysqlite3 is ever removed
PYEOF
printf 'import _pysqlite3_patch\n' > "$SITE_PKGS/_pysqlite3_patch.pth"
ACTUAL=$("$STACK_ROOT/.venv/bin/python3" -c "import sqlite3; print(sqlite3.sqlite_version)")
ok "sqlite3 in venv now: $ACTUAL (via pysqlite3)"

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
# jcodemunch-mcp init always writes a local-scope `uvx jcodemunch-mcp` entry
# which shadows the venv-pinned user-scope registration. Remove it unconditionally
# so the correct venv binary is always what connects.
claude mcp remove jcodemunch -s local   >/dev/null 2>&1 || true
claude mcp remove jcodemunch -s project >/dev/null 2>&1 || true

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

# --- 4d. jdocmunch index-local (initial doc index) --------------------------
# jdocmunch stores its index in ~/.doc-index/. Without an initial indexing
# run the MCP server starts fine but doc_list_repos returns [] and all
# section-search tools are useless. Re-runs are idempotent — the index is
# rebuilt in place, so this step is safe to re-run on upgrades.
step "Indexing project docs with jdocmunch"
if [ -x "${EXE[jdocmunch]}" ]; then
    if "${EXE[jdocmunch]}" index-local --path "$STACK_ROOT" \
            >"$STACK_ROOT/.install-jdm-index.log" 2>&1; then
        ok "jdocmunch doc index created at ~/.doc-index/"
    else
        warn "jdocmunch index-local failed (non-fatal)"
        warn "Re-run manually: ${EXE[jdocmunch]} index-local --path $STACK_ROOT"
        warn "Details: cat $STACK_ROOT/.install-jdm-index.log"
    fi
else
    warn "jdocmunch-mcp binary not found; skipping doc index"
fi

# --- 4e. Download bundled ONNX embedding model ------------------------------
# all-MiniLM-L6-v2 runs locally via ONNX Runtime — no API key required.
# Enables semantic (meaning-based) search alongside BM25/AST.
# Re-runs are idempotent: download-model skips if model already present.
step "Downloading bundled ONNX embedding model (all-MiniLM-L6-v2)"
if [ -x "${EXE[jcodemunch]}" ]; then
    if "${EXE[jcodemunch]}" download-model \
            >"$STACK_ROOT/.install-embed-model.log" 2>&1; then
        ok "embedding model ready at ~/.code-index/models/all-MiniLM-L6-v2"
    else
        warn "download-model failed (non-fatal — semantic search unavailable until resolved)"
        warn "Details: cat $STACK_ROOT/.install-embed-model.log"
    fi
    write_env_var "$STACK_ROOT/.env" "JCODEMUNCH_EMBED_MODEL" "all-MiniLM-L6-v2"
    ok "JCODEMUNCH_EMBED_MODEL=all-MiniLM-L6-v2 set in .env"
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
    mcp_add mempalace -- bash "$STACK_ROOT/scripts/mempalace-mcp-start.sh"
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

# --- 5c. MemPalace health monitoring (cron) ---------------------------------
step "Setting up MemPalace backup + health-check cron jobs"
mkdir -p "$STACK_ROOT/state"
for entry in \
    "uncle-j-mempalace-backup|0 */6 * * * nice -n 19 bash $STACK_ROOT/mempalace-backup.sh >> $STACK_ROOT/state/mempalace-backup.log 2>&1" \
    "uncle-j-mempalace-health|0 8 * * * nice -n 19 $STACK_ROOT/.venv/bin/python $STACK_ROOT/mempalace-health.py >> $STACK_ROOT/state/mempalace-health.log 2>&1" \
    "uncle-j-jcodemunch-reindex|0 1 * * * PATH=/home/bill/.local/bin:/usr/local/bin:/usr/bin:/bin bash $STACK_ROOT/scripts/jcodemunch-reindex.sh >> $STACK_ROOT/state/jcodemunch-reindex.log 2>&1" \
    "uncle-j-auto-maintain|0 3 * * * PATH=/home/bill/.local/bin:/usr/local/bin:/usr/bin:/bin CLAUDE_BIN=/home/bill/.local/bin/claude bash $STACK_ROOT/scripts/auto-maintain.sh >> $STACK_ROOT/state/auto-maintain.log 2>&1" \
    "uncle-j-healthcheck-notify|0 7 * * * bash $STACK_ROOT/scripts/healthcheck-notify.sh >> $STACK_ROOT/state/healthcheck-notify.log 2>&1" \
    "uncle-j-memweave-sync|30 2 * * * nice -n 19 bash $STACK_ROOT/scripts/memweave/sync_memory.sh >> $STACK_ROOT/state/memweave-sync.log 2>&1"
do
    tag="${entry%%|*}"
    line="${entry#*|}"
    install_cron "$tag" "$line"
    ok "cron registered: $tag"
done

# --- 5c2. MemPalace mine crons (project code, conversations, repair, boot) ---
step "Setting up MemPalace mine + repair crons"
bash "$STACK_ROOT/features/mempalace/install.sh"

# --- 5d. Skills (reliability layer) ----------------------------------------
step "Installing global skills (reliability layer)"
bash "$STACK_ROOT/install-reliability.sh" --non-interactive
ok "skills installed"

# --- 5e. jcodemunch index ---------------------------------------------------
step "Indexing repo with jcodemunch"
if bash "$STACK_ROOT/scripts/jcodemunch-reindex.sh"; then
    ok "jcodemunch index up to date"
else
    warn "jcodemunch reindex failed — index may be stale (non-fatal)"
fi

# --- 6. Next-step guidance --------------------------------------------------
step "Next steps"
# --- 6b. Install routing policy (CLAUDE.md) ---------------------------------
step "Installing retrieval routing policy (CLAUDE.md)"
_CLAUDE_SRC="$STACK_ROOT/CLAUDE.md"
_CLAUDE_DEST="$HOME/.claude/CLAUDE.md"
mkdir -p "$HOME/.claude"
if [ -f "$_CLAUDE_DEST" ] && ! diff -q "$_CLAUDE_SRC" "$_CLAUDE_DEST" >/dev/null 2>&1; then
    _BACKUP="$_CLAUDE_DEST.bak.$(date +%Y%m%d%H%M%S)"
    cp "$_CLAUDE_DEST" "$_BACKUP"
    ok "backed up existing CLAUDE.md → $(basename "$_BACKUP")"
    cp "$_CLAUDE_SRC" "$_CLAUDE_DEST"
    ok "routing policy updated → $_CLAUDE_DEST"
elif [ ! -f "$_CLAUDE_DEST" ]; then
    cp "$_CLAUDE_SRC" "$_CLAUDE_DEST"
    ok "routing policy installed → $_CLAUDE_DEST"
else
    ok "routing policy unchanged — skipped"
fi

# --- 6c. Wire git post-merge hook (opt-in) ----------------------------------
step "Optional features"
echo ""
if [[ -d "$STACK_ROOT/.git" ]]; then
    _HOOK_SRC="$STACK_ROOT/scripts/post-merge-hook.sh"
    _HOOK_DEST="$STACK_ROOT/.git/hooks/post-merge"
    if prompt_yes_no "Wire git post-merge hook (alerts on stack changes after git pull)?" n; then
        chmod +x "$_HOOK_SRC"
        ln -sfn "$_HOOK_SRC" "$_HOOK_DEST"
        ok "post-merge hook installed"
    else
        ok "skipped post-merge hook"
    fi

    # Pre-commit hook: session-end documentation gate (always installed — not optional)
    _PRECOMMIT_SRC="$STACK_ROOT/scripts/session-end-check.sh"
    _PRECOMMIT_DEST="$STACK_ROOT/.git/hooks/pre-commit"
    chmod +x "$_PRECOMMIT_SRC"
    ln -sfn "$_PRECOMMIT_SRC" "$_PRECOMMIT_DEST"
    ok "pre-commit hook installed (session-end documentation gate)"
fi

_tg_configured=0
[[ -f "$STACK_ROOT/.env" ]] && grep -q "TELEGRAM_BOT_TOKEN=" "$STACK_ROOT/.env" && _tg_configured=1
if [[ "$_tg_configured" -eq 1 ]]; then
    if prompt_yes_no "Telegram already configured. Overwrite existing credentials?" n; then
        bash "$STACK_ROOT/features/stack-alerts/install.sh"
    else
        ok "Telegram config unchanged"
    fi
fi

# --- 6d. Context7 API key (optional, higher rate limits) --------------------
if [[ "$SKIP_CONTEXT7" -eq 0 ]] && [[ "${NON_INTERACTIVE:-0}" != "1" ]]; then
    _claude_env="$CLAUDE_DIR/.env"
    if [[ -f "$_claude_env" ]] && grep -q "^CONTEXT7_API_KEY=" "$_claude_env"; then
        ok "Context7 API key already configured"
    elif [[ -f "$STACK_ROOT/context7.key" ]]; then
        _c7_key="$(cat "$STACK_ROOT/context7.key")"
        mkdir -p "$(dirname "$_claude_env")"
        write_env_var "$_claude_env" "CONTEXT7_API_KEY" "$_c7_key"
        ok "Context7 API key loaded from context7.key → $_claude_env"
    else
        echo ""
        echo "  Context7 provides version-pinned library docs (React, FastAPI, etc.)"
        echo "  in Claude's context. A free API key raises the rate limit."
        echo "  Get one at: https://context7.com/dashboard"
        echo ""
        prompt_value "Context7 API key (press Enter to skip)" "" _c7_key
        if [[ -n "$_c7_key" ]]; then
            mkdir -p "$(dirname "$_claude_env")"
            write_env_var "$_claude_env" "CONTEXT7_API_KEY" "$_c7_key"
            ok "CONTEXT7_API_KEY written to $_claude_env"
        else
            ok "Context7 API key skipped — add CONTEXT7_API_KEY= to $CLAUDE_DIR/.env later"
        fi
    fi
fi

cat <<EOF

Installed. What to do now:

1. Paste the MCP config fragment into your client:
     Claude Desktop  -> mcp-clients/claude-desktop-config-fragment.json
     Claude Code     -> MCP servers already registered (restart Claude Code to connect)
     Cursor          -> mcp-clients/cursor-mcp.json
     Windsurf        -> mcp-clients/windsurf-mcp.json

2. Bootstrap MemPalace for a project (one-time per project):
     $VENV_BIN/mempalace init ~/path/to/project
     $VENV_BIN/mempalace mine ~/path/to/project
     $VENV_BIN/mempalace mine ~/.claude/projects/ --mode convos

3. Sanity-check:
     ./verify.sh

4. Get free Context7 API key (optional, higher rate limits):
     https://context7.com/dashboard  -> put CONTEXT7_API_KEY=... in ~/.claude/.env

EOF

# MCP servers need a Claude restart to reconnect — skip the live-session
# connectivity check here and tell the user to run it after restart.
cat <<'EOF'

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  INSTALL COMPLETE — one step required:

  MCP servers were registered. Restart Claude Code,
  then run the healthcheck to confirm everything is OK:

      bash healthcheck.sh

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EOF

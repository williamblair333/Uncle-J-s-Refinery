#!/usr/bin/env bash
# finish-install.sh — second-pass installer to run after prerequisites.sh
# in a fresh shell, so PATH picks up newly-installed tools.
#
# Warm-caches Serena + DuckDB MCP (if missed earlier) and auto-registers
# all seven MCP servers with Claude Code at user scope.
#
# Safe to run multiple times.

set -euo pipefail
STACK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$STACK_ROOT"

SKIP_AUTO_REGISTER=0
SKIP_CONTEXT7=0
for arg in "$@"; do
    case "$arg" in
        --skip-auto-register) SKIP_AUTO_REGISTER=1 ;;
        --skip-context7)      SKIP_CONTEXT7=1 ;;
    esac
done

step() { printf '\n==> %s\n'  "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }
has()  { command -v "$1" >/dev/null 2>&1; }

# ── Re-check prerequisites in this shell's PATH ──────────────────────────
step "Re-checking prerequisites"
MISSING=()
for bin in uv uvx git node npx claude; do
    if has "$bin"; then
        ok "$bin available"
    else
        MISSING+=("$bin")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    warn "Missing: ${MISSING[*]}"
    warn "Run ./prerequisites.sh first, open a fresh shell, then re-run this script."
    warn "Or pass --skip-auto-register to skip the pieces that need them."
    [ "$SKIP_AUTO_REGISTER" -eq 0 ] && exit 1
fi

# ── Warm-cache Serena ────────────────────────────────────────────────────
if has uvx && has git; then
    step "Warm-caching Serena via uvx"
    if uvx --from git+https://github.com/oraios/serena serena --help >/dev/null 2>&1; then
        ok "Serena cached"
    else
        warn "Serena warm-cache failed (non-fatal; uvx retries on real invocation)"
    fi
fi

# ── Warm-cache Context7 ──────────────────────────────────────────────────
if [ "$SKIP_CONTEXT7" -eq 0 ] && has npx; then
    step "Testing Context7 (npx -y @upstash/context7-mcp)"
    if npx --yes "@upstash/context7-mcp" --help >/dev/null 2>&1; then
        ok "Context7 resolvable"
    else
        warn "Context7 npx fetch failed — check network / npm registry access"
    fi
fi

# ── Auto-register with Claude Code ───────────────────────────────────────
VENV_BIN="$STACK_ROOT/.venv/bin"
if [ "$SKIP_AUTO_REGISTER" -eq 0 ] && has claude; then
    step "Registering MCP servers with Claude Code (user scope)"
    declare -A CMD=(
        [jcodemunch]="$VENV_BIN/jcodemunch-mcp"
        [jdatamunch]="$VENV_BIN/jdatamunch-mcp"
        [jdocmunch]="$VENV_BIN/jdocmunch-mcp"
    )
    for name in jcodemunch jdatamunch jdocmunch; do
        claude mcp remove "$name" 2>/dev/null || true
        claude mcp add -s user "$name" "${CMD[$name]}"
        ok "registered: $name"
    done

    claude mcp remove mempalace 2>/dev/null || true
    claude mcp add -s user mempalace -- bash "$STACK_ROOT/scripts/mempalace-mcp-start.sh"
    ok "registered: mempalace (via health-check wrapper)"

    claude mcp remove serena 2>/dev/null || true
    claude mcp add -s user serena -- uvx --from git+https://github.com/oraios/serena serena start-mcp-server --context ide-assistant
    ok "registered: serena"

    claude mcp remove duckdb 2>/dev/null || true
    claude mcp add -s user duckdb -- uvx mcp-server-motherduck --db-path :memory: --read-write --allow-switch-databases
    ok "registered: duckdb"

    if [ "$SKIP_CONTEXT7" -eq 0 ] && has npx; then
        claude mcp remove context7 2>/dev/null || true
        claude mcp add -s user context7 -- npx -y "@upstash/context7-mcp"
        ok "registered: context7"
    fi

    step "Listing registered MCP servers"
    claude mcp list
fi

# ── MemPalace health monitoring (cron) ──────────────────────────────────────
step "Setting up MemPalace backup + health-check cron jobs"
mkdir -p "$STACK_ROOT/state"
for entry in \
    "uncle-j-mempalace-backup|0 */6 * * * bash $STACK_ROOT/mempalace-backup.sh >> $STACK_ROOT/state/mempalace-backup.log 2>&1" \
    "uncle-j-mempalace-health|0 8 * * * $STACK_ROOT/.venv/bin/python $STACK_ROOT/mempalace-health.py >> $STACK_ROOT/state/mempalace-health.log 2>&1"
do
    tag="${entry%%|*}"
    line="${entry#*|}"
    if crontab -l 2>/dev/null | grep -q "$tag"; then
        ok "cron already registered: $tag"
    else
        ( crontab -l 2>/dev/null; printf '# %s\n%s\n' "$tag" "$line" ) | crontab -
        ok "cron registered: $tag"
    fi
done

step "Done"
cat <<EOF

Next:
  ./verify.sh                                    # should report all PASS
  ./.venv/bin/mempalace init <project-path>      # bootstrap memory per project
EOF

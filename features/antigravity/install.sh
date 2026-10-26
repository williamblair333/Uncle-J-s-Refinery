#!/usr/bin/env bash
# features/antigravity/install.sh — wire the Refinery into Antigravity CLI (agy).
#
#   1. read-only shell + MCP permission rules  -> ~/.gemini/antigravity-cli/settings.json
#   2. Claude's user-scope MCP servers         -> ~/.gemini/config/mcp_config.json
#   3. routing-policy block (includes CLAUDE.md) -> ~/.gemini/GEMINI.md
#   4. global skills                           -> ~/.gemini/skills (via scripts/skill-link.sh)
#   5. sandbox-run (offline bwrap for code agy runs) -> ~/.local/bin/sandbox-run
#
# Every step merges and keeps a .bak; re-running is safe. Install agy itself first:
# see features/antigravity/README.md.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
PY="$REPO_ROOT/.venv/bin/python"; [[ -x "$PY" ]] || PY=python3

step() { printf '\n==> %s\n' "$*"; }

command -v agy >/dev/null 2>&1 || [[ -x "$HOME/.local/bin/agy" ]] || \
    printf '    !!  agy not found; the config is written anyway and applies once it is installed\n' >&2

step "Permissions";  "$PY" "$HERE/apply_permissions.py"
step "MCP servers";  "$PY" "$HERE/sync_mcp.py"
step "Rules";        "$PY" "$HERE/install_rules.py"
step "Skills";       bash "$REPO_ROOT/scripts/skill-link.sh" link && echo "    linked into ~/.gemini/skills"
step "sandbox-run";  mkdir -p "$HOME/.local/bin" && ln -sfn "$HERE/sandbox-run" "$HOME/.local/bin/sandbox-run" && \
    { command -v bwrap >/dev/null || printf '    !!  bubblewrap (bwrap) not installed: sandbox-run will refuse to run\n' >&2; }

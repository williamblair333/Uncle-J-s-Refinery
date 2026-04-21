#!/usr/bin/env bash
# Post-install sanity check for the Claude retrieval stack (Linux/macOS).

set -u
STACK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_BIN="$STACK_ROOT/.venv/bin"

# Ensure ~/.local/bin (where uv, uvx, and the Claude CLI typically land) is
# visible in this process, mirroring verify.ps1's PATH augmentation. Without
# this, a just-installed stack fails verification until the user opens a new
# shell — which contradicts the one-shot-install goal in the PRD.
case ":$PATH:" in
    *":$HOME/.local/bin:"*) : ;;
    *) export PATH="$HOME/.local/bin:$PATH" ;;
esac

fails=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s -- %s\n' "$1" "$2"; fails=$((fails+1)); }
check() {
    local name="$1"; shift
    if "$@" >/dev/null 2>&1; then pass "$name"; else fail "$name" "exit $?"; fi
}

printf '\n\033[36mVerifying Claude retrieval stack at %s\033[0m\n\n' "$STACK_ROOT"

echo "Python stack (venv binaries):"
check "jcodemunch-mcp --version" "$VENV_BIN/jcodemunch-mcp" --version
check "jdatamunch-mcp --help"    "$VENV_BIN/jdatamunch-mcp" --help
check "jdocmunch-mcp --help"     "$VENV_BIN/jdocmunch-mcp"  --help
check "mempalace --help"         "$VENV_BIN/mempalace"       --help

echo
echo "External helpers:"
check "uv available"     uv  --version
check "uvx available"    uvx --version
check "node available"   node --version
check "npx available"    npx  --version
check "git available"    git  --version
check "claude CLI"       claude --version

echo
echo "uvx-managed servers (may download on first run):"
check "serena --help (via uvx)"          uvx --from git+https://github.com/oraios/serena serena --help
check "mcp-server-motherduck --help"     uvx mcp-server-motherduck --help

# Installer sets web_dashboard_open_on_launch: false in ~/.serena/serena_config.yml
# so Serena doesn't spawn a new browser tab on every Claude Code session start.
check "serena dashboard auto-open disabled" bash -c 'grep -qE "^[[:space:]]*web_dashboard_open_on_launch:[[:space:]]*false" "$HOME/.serena/serena_config.yml"'

echo
echo "Node server (Context7):"
check "@upstash/context7-mcp resolvable" npx --yes "@upstash/context7-mcp" --help

echo
if [ "$fails" -eq 0 ]; then
    printf '\033[32mAll checks passed.\033[0m\n'
    exit 0
else
    printf '\033[31m%d check(s) failed.\033[0m\n' "$fails"
    exit 1
fi

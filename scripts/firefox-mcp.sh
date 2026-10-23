#!/usr/bin/env bash
# firefox-mcp.sh — run Mozilla's firefox-devtools-mcp with a quiet Firefox profile.
#
# Firefox talks only to the sites it's sent to: no telemetry, captive-portal checks, remote
# settings, Safe Browsing, OCSP, DoH, HTTP/3 or update pings. Measured 2026-10-23 with an
# egress capture (see review notes): zero contacts besides the target.
#
#   scripts/firefox-mcp.sh             # stdio MCP server (what Claude Code launches)
#   scripts/firefox-mcp.sh --install   # install the pinned package (needs npm once)
#   scripts/firefox-mcp.sh --config    # print the --mcp-config JSON for one session
#   just browser [claude args]         # start a Claude Code session with it loaded
#
# Not registered globally on purpose: load it per session with `just browser`.
# Env: FIREFOX_MCP_HOME (profile + private config dir, default
# ~/.local/state/uncle-j/firefox-mcp), FIREFOX_MCP_VERSION (default 0.10.4).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
VERSION="${FIREFOX_MCP_VERSION:-0.10.4}"
HOME_DIR="${FIREFOX_MCP_HOME:-${XDG_STATE_HOME:-$HOME/.local/state}/uncle-j/firefox-mcp}"

if [[ "${1:-}" == --config ]]; then
    python3 -c 'import json,sys; print(json.dumps({"mcpServers": {"firefox": {"command": sys.argv[1], "args": []}}}))' \
        "$HERE/firefox-mcp.sh"
    exit 0
fi

# --profilePath DIR makes the server use DIR/firefox_devtools_mcp_profile, and Firefox reads
# user.js from there on every start, so the prefs are re-applied each launch.
PROFILE="$HOME_DIR/firefox_devtools_mcp_profile"
mkdir -p "$PROFILE" "$HOME_DIR/xdg"
cp "$REPO/config/firefox-mcp/user.js" "$PROFILE/user.js"

# Selenium Manager: no usage stats (plausible.io), no driver downloads. geckodriver must be on
# PATH or in ~/.cache/selenium; otherwise the server fetches it from GitHub on first use.
export SE_AVOID_STATS=true SE_OFFLINE=true

# Firefox-side env, passed through moz:firefoxOptions:
# - MOZ_REMOTE_SETTINGS_DEVTOOLS=1: release builds ignore services.settings.server without it.
# - XDG_CONFIG_HOME: a private config dir, so Firefox doesn't pick up the host's own
#   "Crash Reports" store and retry its pending deletion-request ping.
# - MOZ_CRASHREPORTER_DISABLE=1: no crash reporter.
#
# The package is installed once into $HOME_DIR/pkg and run with node directly: `npx` asks
# registry.npmjs.org on every start (and hangs offline). --ignore-scripts skips the geckodriver
# package's postinstall download. Install output goes to stderr: stdout is the MCP channel.
PKG="$HOME_DIR/pkg"
ENTRY="$PKG/node_modules/@mozilla/firefox-devtools-mcp/dist/index.js"
installed=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' \
    "$PKG/node_modules/@mozilla/firefox-devtools-mcp/package.json" 2>/dev/null || true)
if [[ "$installed" != "$VERSION" ]]; then
    printf 'firefox-mcp: installing @mozilla/firefox-devtools-mcp@%s into %s\n' "$VERSION" "$PKG" >&2
    npm install --prefix "$PKG" --ignore-scripts --no-audit --no-fund \
        "@mozilla/firefox-devtools-mcp@$VERSION" >&2
fi
[[ "${1:-}" == --install ]] && exit 0

exec node "$ENTRY" \
    --headless \
    --profilePath "$HOME_DIR" \
    --env MOZ_REMOTE_SETTINGS_DEVTOOLS=1 \
    --env "XDG_CONFIG_HOME=$HOME_DIR/xdg" \
    --env MOZ_CRASHREPORTER_DISABLE=1 \
    "$@"

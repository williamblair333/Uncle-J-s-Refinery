#!/usr/bin/env bash
# Launch jMunch Console — browser GUI for the jMunch MCP suite.
# Upstream: https://github.com/jgravelle/jmunch-console
# Update:   git -C "$(git rev-parse --show-toplevel)/review/jmunch-console" pull
#
# Usage: bash scripts/jmunch-console.sh [port]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONSOLE="$PROJ_ROOT/review/jmunch-console/server.py"
VENV_BIN="$PROJ_ROOT/.venv/bin"
PORT="${1:-8765}"

if [[ ! -f "$CONSOLE" ]]; then
  echo "jmunch-console not cloned yet." >&2
  echo "Run: git clone https://github.com/jgravelle/jmunch-console.git $PROJ_ROOT/review/jmunch-console" >&2
  exit 1
fi

if [[ ! -x "$VENV_BIN/jcodemunch-mcp" ]]; then
  echo "jcodemunch-mcp not found in .venv — run: uv sync --inexact" >&2
  exit 1
fi

export JMUNCH_MCP_BIN="$VENV_BIN/jcodemunch-mcp"
export JMUNCH_CONSOLE_PORT="$PORT"

printf "jMunch Console → http://127.0.0.1:%s\n" "$PORT"
printf "Stop with Ctrl-C\n\n"

exec python3 "$CONSOLE"

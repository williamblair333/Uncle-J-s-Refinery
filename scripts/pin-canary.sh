#!/usr/bin/env bash
# Pin the jcodemunch embedding canary baseline.
#
# Run this when healthcheck reports "embedding canary not pinned".
# Exits 0 on success, 1 on failure.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CANARY="$HOME/.code-index/embed_canary.json"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo 'claude')}"

[[ -f "$PROJ_ROOT/.env" ]] && set -a && source "$PROJ_ROOT/.env" && set +a

if [[ -f "$CANARY" ]]; then
    echo "Canary already pinned: $CANARY"
    exit 0
fi

if ! command -v "$CLAUDE_BIN" &>/dev/null; then
    echo "ERROR: claude binary not found (CLAUDE_BIN=$CLAUDE_BIN)" >&2
    exit 1
fi

echo "Pinning embedding canary via check_embedding_drift(capture=true)..."
"$CLAUDE_BIN" -p \
    "Call the check_embedding_drift MCP tool with capture=true. Do nothing else." \
    2>&1

if [[ ! -f "$CANARY" ]]; then
    echo "ERROR: canary still missing after pin attempt — check claude output above" >&2
    exit 1
fi

echo "Canary pinned: $CANARY ($(wc -c < "$CANARY" | tr -d ' ') bytes)"

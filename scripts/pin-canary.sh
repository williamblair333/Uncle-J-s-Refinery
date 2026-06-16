#!/usr/bin/env bash
# Pin the jcodemunch embedding canary baseline.
#
# Run this when healthcheck reports "embedding canary not pinned".
# Calls capture_canary() directly via the stack venv — no Claude Code session required.
# Exits 0 on success, 1 on failure.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CANARY="$HOME/.code-index/embed_canary.json"
PYTHON="$PROJ_ROOT/.venv/bin/python"

[[ -f "$PROJ_ROOT/.env" ]] && set -a && source "$PROJ_ROOT/.env" && set +a

if [[ -f "$CANARY" ]]; then
    echo "Canary already pinned: $CANARY"
    exit 0
fi

if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: venv python not found at $PYTHON — run install.sh first" >&2
    exit 1
fi

echo "Pinning embedding canary via capture_canary()..."
"$PYTHON" - <<'PYEOF'
from jcodemunch_mcp.retrieval.embed_drift import capture_canary
import json, sys
result = capture_canary()
if result.get("captured"):
    print(f"Canary pinned: {result['path']} ({result['n_canaries']} strings, {result['dim']}d, {result['provider']}/{result['model']})")
else:
    print(f"ERROR: {result.get('error', 'unknown error')}", file=sys.stderr)
    sys.exit(1)
PYEOF

if [[ ! -f "$CANARY" ]]; then
    echo "ERROR: canary file missing after pin attempt" >&2
    exit 1
fi

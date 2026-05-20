#!/usr/bin/env bash
# Incremental jcodemunch index refresh. Safe to run on cron or from post-merge hook.
# Stamps the indexed git HEAD to state/jcodemunch-last-indexed.sha on success.
# Exits 0 on success, 1 on failure.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
JCODEMUNCH="$PROJ_ROOT/.venv/bin/jcodemunch-mcp"
STAMP="$PROJ_ROOT/state/jcodemunch-last-indexed.sha"
LOG="$PROJ_ROOT/state/jcodemunch-reindex.log"

mkdir -p "$PROJ_ROOT/state"
log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

if [[ ! -x "$JCODEMUNCH" ]]; then
    log "ERROR: jcodemunch-mcp not found at $JCODEMUNCH"
    exit 1
fi

log "Starting incremental reindex of $PROJ_ROOT ..."
if "$JCODEMUNCH" index "$PROJ_ROOT" --no-ai-summaries >> "$LOG" 2>&1; then
    SHA=$(git -C "$PROJ_ROOT" rev-parse HEAD 2>/dev/null || echo "unknown")
    echo "$SHA" > "$STAMP"
    log "Reindex complete. Indexed SHA: $SHA"
    exit 0
else
    log "ERROR: jcodemunch-mcp index failed (see above)"
    exit 1
fi

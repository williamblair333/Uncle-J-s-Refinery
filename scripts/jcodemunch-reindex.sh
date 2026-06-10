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

# Prevent concurrent reindex runs (cron + session-start can overlap).
# exec failure (disk full, /tmp not writable) is an error — log and bail rather
# than silently masquerading as a concurrency skip.
LOCK="/tmp/uncle-j-jcodemunch-reindex.lock"
exec 9>"$LOCK" || { log "ERROR: cannot create lock file $LOCK (disk full or /tmp not writable)"; exit 1; }
flock -n 9 || { log "Reindex already running — skipping."; exit 0; }

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

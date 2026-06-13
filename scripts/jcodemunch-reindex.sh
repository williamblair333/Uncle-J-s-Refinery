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

# Per-run output capture. The index call's output goes here so the collision
# check inspects only THIS run, not historical errors accumulated in $LOG.
RUN_OUT="$(mktemp "${TMPDIR:-/tmp}/jcm-reindex.XXXXXX")" || { log "ERROR: cannot create temp file"; exit 1; }
trap 'rm -f "$RUN_OUT"' EXIT

# Run the indexer, capturing this run's output (also tee'd into the persistent log).
run_index() {
    "$JCODEMUNCH" index "$PROJ_ROOT" --no-ai-summaries > "$RUN_OUT" 2>&1
    local rc=$?
    cat "$RUN_OUT" >> "$LOG"
    return $rc
}

# Resolve a dual-identity collision. A stray path-keyed `local/<dir>-<hash>` index
# for this same path makes the default-identity `index` resolve ambiguously and fail
# with "Both local and git identity indexes already match this path". The git-keyed
# identity is canonical for a git repo, so drop the local/ duplicate. Returns 0 if a
# stray was found and deleted (caller should retry), 1 otherwise.
resolve_identity_collision() {
    local stray
    stray=$("$JCODEMUNCH" list-repos --json 2>/dev/null | "$PROJ_ROOT/.venv/bin/python" -c '
import json, os, sys
root = os.path.realpath(sys.argv[1])
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
rows = d if isinstance(d, list) else d.get("repos", [])
for r in rows:
    rid = r.get("repo_id", "")
    src = r.get("source_root") or r.get("path") or r.get("git_root") or ""
    if rid.startswith("local/") and src and os.path.realpath(src) == root:
        print(rid)
        break
' "$PROJ_ROOT")
    if [[ -n "$stray" ]]; then
        log "Identity collision: deleting stray path-keyed index '$stray' (keeping canonical git identity)."
        "$JCODEMUNCH" delete-index "$stray" >> "$LOG" 2>&1
        return 0
    fi
    return 1
}

stamp_success() {
    local sha
    sha=$(git -C "$PROJ_ROOT" rev-parse HEAD 2>/dev/null || echo "unknown")
    echo "$sha" > "$STAMP"
    log "Reindex complete. Indexed SHA: $sha"
}

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
if run_index; then
    stamp_success
    exit 0
elif grep -q "Both local and git identity indexes already match" "$RUN_OUT" \
        && resolve_identity_collision \
        && run_index; then
    log "Reindex succeeded after resolving identity collision."
    stamp_success
    exit 0
else
    log "ERROR: jcodemunch-mcp index failed (see above)"
    exit 1
fi

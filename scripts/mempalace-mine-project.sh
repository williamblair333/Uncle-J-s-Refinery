#!/usr/bin/env bash
# SessionStart hook: mine the current project into MemPalace if not already indexed.
# Runs async — does not block session start banner.
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMPALACE="$PROJ_ROOT/.venv/bin/mempalace"
LOG="$PROJ_ROOT/state/mempalace-mine.log"
LOCK="$PROJ_ROOT/state/mempalace-mine-project.lock"

[[ -x "$MEMPALACE" ]] || exit 0

# Bail if another mine-project is already running; clear stale locks (>30 min)
if ! mkdir "$LOCK" 2>/dev/null; then
  log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }
  LOCK_AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || echo 0) ))
  if [[ "$LOCK_AGE" -gt 1800 ]]; then
    log "mine-project: stale lock (${LOCK_AGE}s) — clearing and proceeding"
    rmdir "$LOCK" 2>/dev/null || true
    mkdir "$LOCK" || { log "mine-project: failed to acquire lock after clearing stale"; exit 1; }
  else
    log "mine-project skipped: already running (lock: $LOCK, age: ${LOCK_AGE}s)"
    exit 0
  fi
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

PALACE_DIR="$HOME/.mempalace/palace"
HNSW_SIZE_LIMIT_MB=200

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

hnsw_check() {
  local label="$1"
  local abort=0
  for f in "$PALACE_DIR"/*/link_lists.bin; do
    [[ -f "$f" ]] || continue
    local sz
    sz=$(du -m "$f" 2>/dev/null | cut -f1)
    if [[ "${sz:-0}" -gt "$HNSW_SIZE_LIMIT_MB" ]]; then
      log "HNSW CORRUPTION ($label): $f is ${sz}MB > ${HNSW_SIZE_LIMIT_MB}MB limit"
      abort=1
    fi
  done
  return "$abort"
}

# Pre-flight: abort if HNSW already corrupted
if ! hnsw_check "pre-mine"; then
  log "mine-project aborted: HNSW already corrupted — run HNSW repair first"
  exit 1
fi

# Read CWD from SessionStart JSON payload (stdin)
PAYLOAD=$(cat)
CWD=$(python3 -c \
  "import sys,json; d=json.loads(sys.argv[1]); print(d.get('cwd',''))" \
  "$PAYLOAD" 2>/dev/null || echo "")

[[ -z "$CWD" || ! -d "$CWD" ]] && exit 0

# Skip system/transient directories
case "$CWD" in
  "$HOME/.claude"*|/tmp*|/var/tmp*|/proc*) exit 0 ;;
esac

# Derive wing name — mempalace convention: basename, lowercase, spaces/hyphens → underscores
WING=$(basename "$CWD" | tr '[:upper:]' '[:lower:]' | tr ' .-' '_')

# Already indexed? Skip to avoid re-mining on every session.
if "$MEMPALACE" status 2>/dev/null | grep -qF "WING: $WING"; then
  exit 0
fi

log "new project detected: $CWD (wing: $WING) — mining"
"$MEMPALACE" mine "$CWD" >> "$LOG" 2>&1 || \
  log "mine-project exited non-zero for $CWD (non-fatal)"

# Post-mine: catch corruption before it grows further
if ! hnsw_check "post-mine"; then
  log "HNSW CORRUPTION DETECTED post-mine — manual repair required"
  log "  1. rm -rf $PALACE_DIR/<uuid>/"
  log "  2. Clear stale locks in state/"
fi

log "done: $WING"

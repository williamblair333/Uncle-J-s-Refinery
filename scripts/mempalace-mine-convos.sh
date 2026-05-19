#!/usr/bin/env bash
# Stop hook: mine Claude session transcripts into MemPalace after every session.
# Runs async — does not block session exit.
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMPALACE="$PROJ_ROOT/.venv/bin/mempalace"
LOG="$PROJ_ROOT/state/mempalace-mine.log"
CONVOS_DIR="$HOME/.claude/projects"
LOCK="$PROJ_ROOT/state/mempalace-mine-convos.lock"

[[ -x "$MEMPALACE" ]] || exit 0
[[ -d "$CONVOS_DIR" ]] || exit 0

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
  log "mine-convos aborted: HNSW already corrupted — run HNSW repair first"
  exit 1
fi

# Bail if another mine-convos is already running; clear stale locks (>30 min)
if ! mkdir "$LOCK" 2>/dev/null; then
  LOCK_AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || echo 0) ))
  if [[ "$LOCK_AGE" -gt 1800 ]]; then
    log "mine-convos: stale lock (${LOCK_AGE}s) — clearing and proceeding"
    rmdir "$LOCK" 2>/dev/null || true
    mkdir "$LOCK" || { log "mine-convos: failed to acquire lock after clearing stale"; exit 1; }
  else
    log "mine-convos skipped: already running (lock: $LOCK, age: ${LOCK_AGE}s)"
    exit 0
  fi
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

log "mining convos: $CONVOS_DIR"
"$MEMPALACE" mine "$CONVOS_DIR" --mode convos --wing conversations >> "$LOG" 2>&1 || \
  log "mine-convos exited non-zero (non-fatal)"

# Post-mine: catch corruption before it grows further
if ! hnsw_check "post-mine"; then
  log "HNSW CORRUPTION DETECTED post-mine — manual repair required"
  log "  1. rm -rf $PALACE_DIR/<uuid>/"
  log "  2. Clear stale locks in state/"
  log "  3. Run: mempalace mine dry-run to verify"
fi

log "done"

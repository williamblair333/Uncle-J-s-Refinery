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

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

# Bail if another mine-convos is already running
if ! mkdir "$LOCK" 2>/dev/null; then
  log "mine-convos skipped: already running (lock: $LOCK)"
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

log "mining convos: $CONVOS_DIR"
"$MEMPALACE" mine "$CONVOS_DIR" --mode convos --wing conversations >> "$LOG" 2>&1 || \
  log "mine-convos exited non-zero (non-fatal)"
log "done"

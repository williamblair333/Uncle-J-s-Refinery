#!/usr/bin/env bash
# Stop hook: mine Claude session transcripts into MemPalace after every session.
# Runs async — does not block session exit.
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMPALACE="$PROJ_ROOT/.venv/bin/mempalace"
LOG="$PROJ_ROOT/state/mempalace-mine.log"
CONVOS_DIR="$HOME/.claude/projects"

[[ -x "$MEMPALACE" ]] || exit 0
[[ -d "$CONVOS_DIR" ]] || exit 0

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

log "mining convos: $CONVOS_DIR"
"$MEMPALACE" mine "$CONVOS_DIR" --mode convos --wing conversations >> "$LOG" 2>&1 || \
  log "mine-convos exited non-zero (non-fatal)"
log "done"

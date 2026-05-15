#!/usr/bin/env bash
# SessionStart hook: mine the current project into MemPalace if not already indexed.
# Runs async — does not block session start banner.
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMPALACE="$PROJ_ROOT/.venv/bin/mempalace"
LOG="$PROJ_ROOT/state/mempalace-mine.log"
LOCK="$PROJ_ROOT/state/mempalace-mine-project.lock"

[[ -x "$MEMPALACE" ]] || exit 0

# Bail if another mine-project is already running
if ! mkdir "$LOCK" 2>/dev/null; then
  log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }
  log "mine-project skipped: already running (lock: $LOCK)"
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

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
log "done: $WING"

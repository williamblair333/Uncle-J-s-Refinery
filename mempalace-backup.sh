#!/usr/bin/env bash
# MemPalace rotating backup — keeps 3 snapshots.
# Usage: mempalace-backup.sh [palace_path] [backup_root]
set -euo pipefail

PALACE="${1:-$HOME/.mempalace/palace}"
BACKUP_ROOT="${2:-$HOME/.mempalace-backups}"
KEEP=3

if [[ ! -d "$PALACE" ]]; then
    echo "ERROR: palace not found at $PALACE" >&2
    exit 1
fi

mkdir -p "$BACKUP_ROOT"

STAMP=$(date +%Y%m%d-%H%M%S)
DEST="$BACKUP_ROOT/palace-$STAMP"

# rsync preserves hardlinks and skips unchanged files.
# Exit 24 = "some files vanished" (SQLite journals) — safe to ignore.
rsync -a --delete "$PALACE/" "$DEST/" || { rc=$?; [[ $rc -eq 24 ]] || { echo "ERROR: rsync failed ($rc)"; exit $rc; }; }
echo "$(date -Iseconds) backup -> $DEST ($(du -sh "$DEST" | cut -f1))"

# Rotate: remove oldest if we exceed KEEP
mapfile -t snapshots < <(ls -1d "$BACKUP_ROOT"/palace-* 2>/dev/null | sort)
excess=$(( ${#snapshots[@]} - KEEP ))
for (( i=0; i<excess; i++ )); do
    rm -rf "${snapshots[$i]}"
    echo "$(date -Iseconds) removed old backup ${snapshots[$i]}"
done

# Run health check after backup
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/mempalace-health.py" ]]; then
    /opt/proj/Uncle-J-s-Refinery/.venv/bin/python "$SCRIPT_DIR/mempalace-health.py" || true
fi

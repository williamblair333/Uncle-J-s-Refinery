#!/usr/bin/env bash
# Post-repair verification: waits until the repair lock is free, then checks
# that HNSW count is within 5% of SQLite count. Writes a one-line summary to
# the repair log and a sentinel file so the polling cron stops firing.
# Run by the uncle-j-mempalace-repair-verify cron every 30 min.
set -uo pipefail

VENV="/opt/proj/Uncle-J-s-Refinery/.venv/bin"
LOG="/opt/proj/Uncle-J-s-Refinery/state/mempalace-repair.log"
SENTINEL="/tmp/mempalace-verify-done"
PALACE="$HOME/.mempalace/palace"
DB="$PALACE/chroma.sqlite3"
export CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [verify] $*" | tee -a "$LOG"; }

# Skip if already verified this repair cycle
[ -f "$SENTINEL" ] && exit 0

# Skip if repair is still running (flock held)
if ! flock -n /tmp/mempalace-repair.lock true 2>/dev/null; then
  log "Repair still running — skipping verification (will retry)"
  exit 0
fi

log "==> Repair lock released — running post-repair verification..."

# Get counts from Python (not the system sqlite3 CLI — version mismatch)
SQLITE_COUNT=$("$VENV/python3" -c "
import sqlite3, pathlib
db = str(pathlib.Path.home() / '.mempalace' / 'palace' / 'chroma.sqlite3')
conn = sqlite3.connect(db, timeout=30)
print(conn.execute('SELECT COUNT(*) FROM embedding_metadata').fetchone()[0])
" 2>/dev/null || echo "0")

HNSW_COUNT=$("$VENV/python3" - <<'PYEOF' 2>/dev/null || echo "0"
import sqlite3, struct, pathlib

palace = pathlib.Path.home() / '.mempalace' / 'palace'
db = palace / 'chroma.sqlite3'
total = 0
with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as conn:
    segs = conn.execute("SELECT s.id FROM segments s WHERE s.scope='VECTOR'").fetchall()
for (seg_id,) in segs:
    hdr = palace / seg_id / 'header.bin'
    if not hdr.exists():
        continue
    data = hdr.read_bytes()
    if len(data) < 24:
        continue
    max_el, = struct.unpack_from('<Q', data, 8)
    # Only count sane values (< 500B)
    if max_el < 500_000_000_000:
        total += max_el
print(total)
PYEOF
)

log "SQLite embeddings: $SQLITE_COUNT"
log "HNSW elements:     $HNSW_COUNT"

if [ "$SQLITE_COUNT" -gt 0 ] && [ "$HNSW_COUNT" -gt 0 ]; then
  OK=$("$VENV/python3" -c "
s, h = $SQLITE_COUNT, $HNSW_COUNT
ratio = h / s
ok = ratio >= 0.95
print(f'ratio={ratio:.3f}  ok={ok}')
import sys; sys.exit(0 if ok else 1)
" 2>/dev/null)
  if [ $? -eq 0 ]; then
    log "VERIFY_RESULT=success  $OK"
    touch "$SENTINEL"
  else
    log "VERIFY_RESULT=fail  $OK  — HNSW count too low, repair may not have completed cleanly"
  fi
elif [ "$HNSW_COUNT" -eq 0 ]; then
  log "VERIFY_RESULT=fail  HNSW count is 0 — repair did not rebuild the index"
else
  log "VERIFY_RESULT=unknown  sqlite=$SQLITE_COUNT hnsw=$HNSW_COUNT"
fi

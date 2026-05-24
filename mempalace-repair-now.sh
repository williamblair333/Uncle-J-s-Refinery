#!/usr/bin/env bash
# Automated recovery: fix FTS5 corruption then rebuild HNSW index.
# Called by the 4am cron and on @reboot; safe to run manually too.
# Idempotent — safe to re-run.
set -uo pipefail  # NOT -e: errors handled explicitly with REPAIR_RESULT tracking

VENV="/opt/proj/Uncle-J-s-Refinery/.venv/bin"
PALACE="$HOME/.mempalace/palace"
DB="$PALACE/chroma.sqlite3"
export CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI

FTS5_STATUS="not_run"
HNSW_STATUS="not_run"
REPAIR_RESULT="unknown"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# --- Active writer check ---
log "==> Checking for active writers..."
for pid in $(fuser "$DB" 2>/dev/null || true); do
  cmd=$(ps -p "$pid" -o cmd= 2>/dev/null || echo "unknown")
  log "  PID $pid: $cmd"
  if echo "$cmd" | grep -qE "mine|repair"; then
    log "  [WARN] mine/repair process active — aborting"
    REPAIR_RESULT="aborted_writer_active"
    log "REPAIR_RESULT=$REPAIR_RESULT"
    exit 1
  fi
done

# Use the venv Python for all SQLite checks — the system sqlite3 CLI (3.46.1) misreads
# FTS5 indexes written by the venv's SQLite 3.50.x and reports false-positive corruption.
pycheck() {
  "$VENV/python3" -c "
import sqlite3, pathlib, sys
db = str(pathlib.Path.home() / '.mempalace' / 'palace' / 'chroma.sqlite3')
$1
" 2>/dev/null
}

# --- Pre-repair drawer count ---
PRE_COUNT=$(pycheck "conn=sqlite3.connect(db); print(conn.execute('SELECT COUNT(*) FROM embedding_metadata').fetchone()[0])" || echo "0")
log "Pre-repair embedding count: $PRE_COUNT"

# --- Step 1: FTS5 rebuild ---
log "==> Checking FTS5 health..."
QC_PRE=$(pycheck "conn=sqlite3.connect(db); print(conn.execute('PRAGMA quick_check').fetchone()[0])" || echo "error")
log "  quick_check (pre): $QC_PRE"

if [ "$QC_PRE" != "ok" ]; then
  log "==> FTS5 corruption detected — attempting rebuild..."
  if "$VENV/python" - <<'PYEOF' 2>&1; then
import sqlite3, pathlib
db = str(pathlib.Path.home() / '.mempalace' / 'palace' / 'chroma.sqlite3')
conn = sqlite3.connect(db, timeout=60)
conn.execute("INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('rebuild')")
conn.commit()
qc = conn.execute("PRAGMA quick_check").fetchone()[0]
print(f"  quick_check (post-rebuild): {qc}")
if qc != 'ok':
    raise RuntimeError(f"quick_check still failing after rebuild: {qc}")
conn.close()
PYEOF
    FTS5_STATUS="rebuilt_ok"
    log "  FTS5 rebuild: OK"
  else
    FTS5_STATUS="rebuild_failed"
    log "  [WARN] FTS5 rebuild failed — skipping HNSW repair to avoid data loss"
    REPAIR_RESULT="fts5_rebuild_failed"
    log "REPAIR_RESULT=$REPAIR_RESULT  fts5=$FTS5_STATUS  hnsw=$HNSW_STATUS"
    exit 1
  fi
else
  FTS5_STATUS="already_ok"
  log "  FTS5 already healthy"
fi

# Final gate: confirm quick_check passes before touching HNSW
QC_POST=$(pycheck "conn=sqlite3.connect(db); print(conn.execute('PRAGMA quick_check').fetchone()[0])" || echo "error")
if [ "$QC_POST" != "ok" ]; then
  log "  [WARN] PRAGMA quick_check still reports: $QC_POST"
  log "  Skipping HNSW repair — DB not clean"
  REPAIR_RESULT="qc_still_failing"
  log "REPAIR_RESULT=$REPAIR_RESULT  fts5=$FTS5_STATUS  hnsw=$HNSW_STATUS"
  exit 1
fi

# --- Step 2: Discover and clear corrupt HNSW segments ---
log "==> Discovering corrupt HNSW segments..."
"$VENV/python" - <<'PYEOF' 2>&1
import sqlite3, struct, pathlib

palace = pathlib.Path.home() / '.mempalace' / 'palace'
db = palace / 'chroma.sqlite3'
with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as conn:
    rows = conn.execute("SELECT s.id FROM segments s WHERE s.scope='VECTOR'").fetchall()

corrupt = []
for (seg_id,) in rows:
    seg_dir = palace / seg_id
    ll = seg_dir / 'link_lists.bin'
    hdr = seg_dir / 'header.bin'
    if not hdr.exists():
        continue
    ll_size = ll.stat().st_size if ll.exists() else 0
    data = hdr.read_bytes()
    if len(data) < 24:
        continue
    max_el, = struct.unpack_from('<Q', data, 8)
    # Corrupt headers have astronomical max_el values (trillions+).
    # Realistic ceiling: 500M drawers × 1000x headroom = 5×10^11.
    if ll_size > 100_000_000 or max_el > 500_000_000_000:
        corrupt.append(seg_id)
        print(f'  CORRUPT: {seg_id} (link_lists={ll_size}B max_el={max_el:,})')
    else:
        print(f'  ok: {seg_id} (link_lists={ll_size}B max_el={max_el:,})')

with open('/tmp/corrupt_segs.txt', 'w') as f:
    for s in corrupt:
        f.write(s + '\n')
PYEOF

log "==> Clearing corrupt HNSW binaries..."
while IFS= read -r seg; do
  dir="$PALACE/$seg"
  log "  Clearing $seg"
  for f in header.bin link_lists.bin data_level0.bin index_metadata.pickle; do
    [ -f "$dir/$f" ] && rm "$dir/$f" && log "    deleted $f" || true
  done
done < /tmp/corrupt_segs.txt
rm -f /tmp/corrupt_segs.txt

# --- Step 3: Rebuild HNSW from SQLite ---
log "==> Running mempalace repair..."
REPAIR_OUT=$("$VENV/mempalace" repair --yes 2>&1)
REPAIR_EXIT=$?
echo "$REPAIR_OUT"
if [ $REPAIR_EXIT -ne 0 ] || echo "$REPAIR_OUT" | grep -q "Aborted"; then
  HNSW_STATUS="repair_failed"
  log "  [WARN] mempalace repair failed (exit=$REPAIR_EXIT)"
  REPAIR_RESULT="hnsw_repair_failed"
  log "REPAIR_RESULT=$REPAIR_RESULT  fts5=$FTS5_STATUS  hnsw=$HNSW_STATUS"
  exit 1
fi
HNSW_STATUS="rebuilt_ok"
log "  mempalace repair: OK"

# --- Post-repair drawer count sanity check ---
POST_COUNT=$(pycheck "conn=sqlite3.connect(db); print(conn.execute('SELECT COUNT(*) FROM embedding_metadata').fetchone()[0])" || echo "0")
log "Post-repair embedding count: $POST_COUNT"
if [ "$PRE_COUNT" -gt 0 ] && [ "$POST_COUNT" -gt 0 ]; then
  if python3 -c "import sys; sys.exit(0 if $POST_COUNT >= $PRE_COUNT * 0.95 else 1)" 2>/dev/null; then
    log "  Count check: OK ($POST_COUNT / $PRE_COUNT = within 5%)"
  else
    log "  [WARN] Drawer count dropped >5% (pre=$PRE_COUNT post=$POST_COUNT) — investigate"
  fi
fi

# --- Health check ---
log "==> Running health check..."
"$VENV/python" /opt/proj/Uncle-J-s-Refinery/mempalace-health.py 2>&1 || true

REPAIR_RESULT="success"
log "REPAIR_RESULT=$REPAIR_RESULT  fts5=$FTS5_STATUS  hnsw=$HNSW_STATUS"
log "Done."

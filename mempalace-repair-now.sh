#!/usr/bin/env bash
# Automated recovery: fix FTS5 corruption then rebuild HNSW index.
# Called by the 4am cron and on @reboot; safe to run manually too.
# Idempotent — safe to re-run.
set -uo pipefail  # NOT -e: errors handled explicitly with REPAIR_RESULT tracking

VENV="/opt/proj/Uncle-J-s-Refinery/.venv/bin"
REPO_ROOT="/opt/proj/Uncle-J-s-Refinery"
PALACE="$HOME/.mempalace/palace"
DB="$PALACE/chroma.sqlite3"
export CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI

FTS5_STATUS="not_run"
HNSW_STATUS="not_run"
REPAIR_RESULT="unknown"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

notify() {
  local msg=$1
  if [[ -f "$REPO_ROOT/lib/notify.sh" ]]; then
    source "$REPO_ROOT/lib/notify.sh"
    notify_send_text "$msg" 2>/dev/null || true
  fi
}

# --- Active writer check ---
log "==> Checking for active writers..."
for pid in $(fuser "$DB" 2>/dev/null || true); do
  cmd=$(ps -p "$pid" -o cmd= 2>/dev/null || echo "unknown")
  log "  PID $pid: $cmd"
  if echo "$cmd" | grep -qE "mine|repair"; then
    log "  [WARN] mine/repair process active — aborting"
    REPAIR_RESULT="aborted_writer_active"
    log "REPAIR_RESULT=$REPAIR_RESULT"
    notify "⚠️ MemPalace repair aborted — active writer (PID $pid) still running. Will retry at next cron window."
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
PRE_COUNT=$(pycheck "conn=sqlite3.connect(db); print(conn.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0])" || echo "0")
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
    notify "❌ MemPalace repair FAILED — FTS5 rebuild could not fix SQLite corruption. Manual recovery needed."
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

# --- Step 2: Rebuild palace from SQLite (bypasses corrupt HNSW entirely) ---
# --mode from-sqlite reads (id, document, metadata) directly from chroma.sqlite3,
# never opens a chromadb client against the corrupt HNSW files, and rebuilds a
# fresh palace. --archive-existing renames the corrupt palace before rebuilding
# so it can be restored if needed: mv ~/.mempalace/palace.pre-rebuild-* ~/.mempalace/palace
log "==> Running mempalace repair (from-sqlite mode)..."
REPAIR_OUT=$("$VENV/mempalace" repair --mode from-sqlite --yes --archive-existing 2>&1)
REPAIR_EXIT=$?
echo "$REPAIR_OUT"
if [ $REPAIR_EXIT -ne 0 ]; then
  HNSW_STATUS="repair_failed"
  log "  [WARN] mempalace repair failed (exit=$REPAIR_EXIT)"
  REPAIR_RESULT="hnsw_repair_failed"
  log "REPAIR_RESULT=$REPAIR_RESULT  fts5=$FTS5_STATUS  hnsw=$HNSW_STATUS"
  notify "❌ MemPalace repair FAILED (exit=$REPAIR_EXIT) — HNSW rebuild did not complete. Check repair log."
  exit 1
fi
HNSW_STATUS="rebuilt_ok"
log "  mempalace repair: OK"

# --- Post-repair drawer count sanity check ---
POST_COUNT=$(pycheck "conn=sqlite3.connect(db); print(conn.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0])" || echo "0")
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
notify "✅ MemPalace repair complete — HNSW rebuilt from SQLite ($POST_COUNT embeddings). Palace ready; MCP server picks it up automatically on next session start."

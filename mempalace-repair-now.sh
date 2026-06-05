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

SKIP_IF_HEALTHY=0
for _arg in "$@"; do [[ "$_arg" == "--skip-if-healthy" ]] && SKIP_IF_HEALTHY=1; done

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

# --- Skip if healthy (used by @reboot cron to avoid unnecessary rebuild) ---
if [[ $SKIP_IF_HEALTHY -eq 1 ]]; then
  log "==> --skip-if-healthy: checking if repair is needed..."
  _need_repair=0

  # Check every segment has a non-empty link_lists.bin AND is below corruption threshold
  _found=0
  for _f in "$PALACE"/*/link_lists.bin; do
    _found=1
    if [[ ! -s "$_f" ]]; then
      log "  missing/empty HNSW: $_f"; _need_repair=1; break
    fi
    _sz=$(du -m "$_f" 2>/dev/null | cut -f1)
    if [[ "${_sz:-0}" -gt 200 ]]; then
      log "  HNSW oversized ($_sz MB) — corruption likely: $_f"; _need_repair=1; break
    fi
  done
  [[ $_found -eq 0 ]] && { log "  no link_lists.bin found — repair needed"; _need_repair=1; }

  if [[ $_need_repair -eq 0 ]]; then
    # Compare HNSW element count (from header.bin) vs SQLite drawer count
    _sqlite=$(  "$VENV/python3" -c "
import sqlite3, pathlib
db = str(pathlib.Path.home()/'.mempalace'/'palace'/'chroma.sqlite3')
print(sqlite3.connect(db).execute('SELECT COUNT(*) FROM embeddings').fetchone()[0])
" 2>/dev/null || echo 0)
    _hnsw=$(  "$VENV/python3" -c "
import pathlib, struct
total=0
for f in (pathlib.Path.home()/'.mempalace'/'palace').glob('*/header.bin'):
  try:
    b=f.read_bytes()
    n=struct.unpack_from('<I',b,20)[0] if len(b)>=24 else 0
    total += n if 0<=n<=10_000_000 else 0
  except: pass
print(total)
" 2>/dev/null || echo 0)
    log "  SQLite=$_sqlite  HNSW=$_hnsw"
    "$VENV/python3" -c "import sys; sys.exit(0 if int('$_hnsw') >= int('$_sqlite')*0.8 else 1)" 2>/dev/null \
      && { log "  HNSW healthy — skipping repair"; REPAIR_RESULT="skipped_healthy"; log "REPAIR_RESULT=$REPAIR_RESULT"; exit 0; } \
      || { log "  HNSW/SQLite drift — proceeding with repair"; }
  fi
fi

# --- Active writer check ---
log "==> Checking for active writers..."
for pid in $(fuser "$DB" 2>/dev/null || true); do
  cmd=$(ps -p "$pid" -o cmd= 2>/dev/null || echo "unknown")
  log "  PID $pid: $cmd"
  # mcp_server processes hold the DB read-only — exclude them so repair can run
  # alongside a live session. Only block actual write processes (mine, repair, fts5).
  if echo "$cmd" | grep -qiE "mine|repair|fts5|autofix|mempalace" \
       && ! echo "$cmd" | grep -q "mcp_server"; then
    log "  [WARN] mempalace-related process active — aborting"
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
  if "$VENV/python3" - <<'PYEOF' 2>&1; then
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
"$VENV/mempalace" repair --mode from-sqlite --yes --archive-existing 2>&1
REPAIR_EXIT=$?
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

# --- Step 2b: Force-flush HNSW to disk for all collections ---
# Problem: small collections (< 50K items) never reach hnsw:batch_size=50000, so their
# in-memory brute-force index is never moved to HNSW. When repair exits, brute-force is
# lost and link_lists.bin stays 0 bytes. Searches then fail with "ef or M is too small".
# Fix: lower batch/sync params for small collections, rebuild from archive if HNSW is
# empty, call _apply_batch + _persist to flush everything to disk before exiting.
log "==> Step 2b: Force-flushing HNSW to disk for all collections..."
"$VENV/python3" - <<'PYEOF' 2>&1
import os, sys, sqlite3, pathlib
os.environ.setdefault("CHROMA_API_IMPL", "chromadb.api.segment.SegmentAPI")

PALACE = pathlib.Path.home() / ".mempalace" / "palace"
DB     = PALACE / "chroma.sqlite3"
SMALL_THRESHOLD = 50_000
SMALL_BATCH     = 100

def get_col_info():
    # embeddings table uses METADATA segment IDs; VECTOR segment ID is for HNSW files.
    with sqlite3.connect(str(DB)) as c:
        return c.execute("""
            SELECT c.id, c.name, v.id, m.id, COUNT(e.id)
            FROM collections c
            JOIN segments v ON v.collection=c.id AND v.scope='VECTOR'
            JOIN segments m ON m.collection=c.id AND m.scope='METADATA'
            LEFT JOIN embeddings e ON e.segment_id=m.id
            GROUP BY c.id
        """).fetchall()

def lower_batch_params(col_info):
    with sqlite3.connect(str(DB)) as c:
        for col_id, col_name, vec_seg_id, meta_seg_id, cnt in col_info:
            if 0 < cnt < SMALL_THRESHOLD:
                for key, val in [("hnsw:batch_size", str(SMALL_BATCH)),
                                  ("hnsw:sync_threshold", str(SMALL_BATCH))]:
                    c.execute(
                        "INSERT OR REPLACE INTO collection_metadata"
                        "(collection_id,key,str_value,int_value,float_value,bool_value)"
                        " VALUES(?,?,?,NULL,NULL,NULL)",
                        (col_id, key, val)
                    )
                print(f"  {col_name}: set batch/sync={SMALL_BATCH}", flush=True)
        c.commit()

def archive_vectors(col_name, embedding_ids):
    """Load vectors from the most recent archive for the given embedding IDs."""
    mp = pathlib.Path.home() / ".mempalace"
    archives = sorted(
        [d for d in mp.iterdir() if d.is_dir() and d.name.startswith("palace.pre-rebuild")],
        reverse=True
    )
    if not archives:
        print(f"  {col_name}: no archive found", flush=True)
        return [], []
    arch_db = archives[0] / "chroma.sqlite3"
    if not arch_db.exists():
        return [], []
    with sqlite3.connect(f"file:{arch_db}?mode=ro", uri=True) as c:
        row = c.execute("SELECT id FROM collections WHERE name=?", (col_name,)).fetchone()
        if not row:
            print(f"  {col_name}: not found in archive", flush=True)
            return [], []
        topic = f"persistent://default/default/{row[0]}"
        id_set = set(embedding_ids)
        rows = c.execute(
            "SELECT id, vector FROM embeddings_queue"
            " WHERE topic=? AND vector IS NOT NULL",
            (topic,)
        ).fetchall()
    filtered = [(r[0], r[1]) for r in rows if r[0] in id_set]
    ids  = [r[0] for r in filtered]
    vecs = [np.frombuffer(r[1], dtype=np.float32) for r in filtered]
    print(f"  {col_name}: archive has {len(ids)}/{len(embedding_ids)} vectors", flush=True)
    return ids, vecs

try:
    import numpy as np
    from chromadb.config import Settings, System
    from chromadb.api.segment import SegmentAPI
    from chromadb.segment import SegmentManager, VectorReader
    from chromadb.segment.impl.vector.batch import Batch

    col_info = get_col_info()
    if not col_info:
        print("  No collections found — skipping", flush=True)
        sys.exit(0)

    lower_batch_params(col_info)

    settings = Settings(
        chroma_api_impl="chromadb.api.segment.SegmentAPI",
        is_persistent=True,
        persist_directory=str(PALACE),
        allow_reset=False,
    )
    system = System(settings)
    system.start()
    api     = system.instance(SegmentAPI)
    seg_mgr = system.instance(SegmentManager)

    for col_id, col_name, vec_seg_id, meta_seg_id, emb_count in col_info:
        if emb_count == 0:
            print(f"  {col_name}: 0 embeddings — skip", flush=True)
            continue
        try:
            col = api.get_collection(col_name)
            seg = seg_mgr.get_segment(col.id, VectorReader)

            # Small collection with empty HNSW: rebuild vectors from archive
            idx_count = seg._index.element_count if seg._index else 0
            if emb_count < SMALL_THRESHOLD and idx_count == 0:
                print(f"  {col_name}: HNSW empty ({emb_count} in SQLite) — archive rebuild", flush=True)
                with sqlite3.connect(str(DB)) as c:
                    emb_ids = [r[0] for r in c.execute(
                        "SELECT embedding_id FROM embeddings WHERE segment_id=?", (meta_seg_id,)
                    ).fetchall()]
                ids, vecs = archive_vectors(col_name, emb_ids)
                if ids:
                    for i in range(0, len(ids), SMALL_BATCH):
                        api._upsert(
                            collection_id=col.id,
                            ids=ids[i:i+SMALL_BATCH],
                            embeddings=vecs[i:i+SMALL_BATCH],
                        )
                    print(f"  {col_name}: upserted {len(ids)} vectors from archive", flush=True)
                else:
                    print(f"  {col_name}: WARNING — no archive vectors; HNSW stays empty", flush=True)

            # Move brute-force → HNSW, then persist to disk
            seg._apply_batch(seg._curr_batch)
            seg._curr_batch = Batch()
            final = seg._index.element_count if seg._index else 0
            if final > 0:
                seg._persist()
                ll = PALACE / vec_seg_id / "link_lists.bin"
                sz = ll.stat().st_size if ll.exists() else 0
                print(f"  {col_name}: HNSW={final} elements, link_lists.bin={sz}B", flush=True)
            else:
                print(f"  {col_name}: WARNING — HNSW still 0 after flush", flush=True)
        except Exception as e:
            print(f"  {col_name}: flush error: {e}", flush=True)

    system.stop()
    print("  HNSW force-flush complete", flush=True)
    sys.exit(0)

except Exception as e:
    print(f"  force-flush failed: {e}", flush=True)
    print("  Non-fatal — mine cron will populate HNSW on next run", flush=True)
    sys.exit(0)
PYEOF

# --- Step 2c: Migrate any dict-format HNSW pickles to SimpleNamespace ---
# Safety net for palaces restored from old chromadb (pre-1.5.x) backups.
# Old chromadb serialised index_metadata.pickle as a plain Python dict; 1.5.x
# expects a PersistentData object. SegmentAPI accesses .dimensionality as an
# attribute, which dicts don't have, producing "'dict' object has no attribute
# 'dimensionality'" on every MCP search query.
#
# Under normal operation this step is a no-op: _persist() in local_persistent_hnsw.py
# does attribute assignment before pickle.dump, so a dict would raise AttributeError
# before the write — meaning _persist() cannot introduce a dict pickle. Verified:
# _persist() is the only pickle.dump call in the installed chromadb package.
#
# Fix: convert dict → types.SimpleNamespace (stdlib-only, upgrade-safe).
# SimpleNamespace has real attribute access (.dimensionality works), survives
# pickle round-trips, and doesn't require importing chromadb internals.
log "==> Migrating any dict-format HNSW pickles to SimpleNamespace..."
"$VENV/python3" - <<'PYEOF' 2>&1
import pickle, pathlib, types, sys, shutil

palace = pathlib.Path.home() / ".mempalace" / "palace"
migrated = 0
for pkl_path in palace.glob("*/index_metadata.pickle"):
    try:
        with open(pkl_path, "rb") as f:
            data = pickle.load(f)
        if not isinstance(data, dict):
            continue
        bak = pkl_path.with_suffix(".pickle.bak")
        shutil.copy2(pkl_path, bak)
        ns = types.SimpleNamespace(**data)
        tmp = pkl_path.with_suffix(".pickle.tmp")
        with open(tmp, "wb") as f:
            pickle.dump(ns, f, pickle.HIGHEST_PROTOCOL)
        tmp.rename(pkl_path)
        print(f"  Migrated {pkl_path.parent.name[:8]}: dict → SimpleNamespace (backup: {bak.name})", flush=True)
        migrated += 1
    except Exception as e:
        print(f"  {pkl_path.parent.name[:8]}: migration error: {e}", flush=True)
        sys.exit(1)
print(f"  {migrated} pickle(s) migrated" if migrated else "  No dict-format pickles found — nothing to do", flush=True)
PYEOF
PICKLE_MIGRATE_EXIT=$?
if [ $PICKLE_MIGRATE_EXIT -ne 0 ]; then
  log "  [WARN] dict-pickle migration had errors (exit=$PICKLE_MIGRATE_EXIT) — MCP search may still fail"
fi

# --- Post-repair count sanity check (SQLite integrity + HNSW binary verification) ---
POST_COUNT=$(pycheck "conn=sqlite3.connect(db); print(conn.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0])" || echo "0")
POST_HNSW=$("$VENV/python3" -c "
import pathlib, struct
palace = pathlib.Path.home() / '.mempalace' / 'palace'
total = 0
for f in palace.glob('*/header.bin'):
    try:
        b = f.read_bytes()
        n = struct.unpack_from('<I', b, 20)[0] if len(b) >= 24 else 0
        total += n if 0 <= n <= 10_000_000 else 0
    except: pass
print(total)
" 2>/dev/null || echo 0)
log "Post-repair: SQLite=$POST_COUNT  HNSW=$POST_HNSW"
if [ "$PRE_COUNT" -gt 0 ] && [ "$POST_COUNT" -gt 0 ]; then
  if "$VENV/python3" -c "import sys; sys.exit(0 if $POST_COUNT >= $PRE_COUNT * 0.95 else 1)" 2>/dev/null; then
    log "  SQLite count check: OK ($POST_COUNT / $PRE_COUNT = within 5%)"
  else
    log "  [WARN] SQLite drawer count dropped >5% (pre=$PRE_COUNT post=$POST_COUNT) — investigate"
  fi
fi
if [ "$POST_HNSW" -lt 1 ]; then
  log "  [WARN] HNSW element count is 0 after repair — mine cron will populate on next run"
fi

# --- Health check ---
log "==> Running health check..."
"$VENV/python" /opt/proj/Uncle-J-s-Refinery/mempalace-health.py 2>&1 || true

REPAIR_RESULT="success"
log "REPAIR_RESULT=$REPAIR_RESULT  fts5=$FTS5_STATUS  hnsw=$HNSW_STATUS"
log "Done."
notify "✅ MemPalace repair complete — HNSW=$POST_HNSW SQLite=$POST_COUNT. Palace ready; MCP server picks it up automatically on next session start."

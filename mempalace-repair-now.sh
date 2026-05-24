#!/usr/bin/env bash
# Run immediately after restarting Claude Code (before any mine jobs run).
# Rebuilds corrupted HNSW index from intact SQLite data.
# Safe to re-run; idempotent.
set -euo pipefail

VENV="/opt/proj/Uncle-J-s-Refinery/.venv/bin"
PALACE="$HOME/.mempalace/palace"
# Force Python segment API — default RustBindingsAPI has HNSW type-confusion bug
export CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI

echo "==> Checking for active writers..."
for pid in $(fuser "$PALACE/chroma.sqlite3" 2>/dev/null || true); do
  cmd=$(ps -p "$pid" -o cmd= 2>/dev/null || echo "unknown")
  echo "  PID $pid: $cmd"
  if echo "$cmd" | grep -qE "mine|repair"; then
    echo "  [WARN] mine/repair process still running — wait for it to finish or kill it first"
    exit 1
  fi
done

echo "==> Rebuilding FTS5 index..."
"$VENV/python" - <<'PYEOF'
import sqlite3
db = f"{__import__('pathlib').Path.home()}/.mempalace/palace/chroma.sqlite3"
conn = sqlite3.connect(db, timeout=30)
conn.execute("INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('rebuild')")
conn.commit()
qc = conn.execute("PRAGMA quick_check").fetchone()[0]
print(f"  quick_check: {qc}")
conn.close()
PYEOF

echo "==> Discovering corrupt HNSW segments from SQLite..."
"$VENV/python" - <<'PYEOF'
import sqlite3, struct, pathlib, sys

palace = pathlib.Path.home() / '.mempalace' / 'palace'
db = palace / 'chroma.sqlite3'
with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as conn:
    rows = conn.execute(
        "SELECT s.id FROM segments s WHERE s.scope='VECTOR'"
    ).fetchall()

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
    # Detect corruption: link_lists.bin > 100MB, OR astronomical header values
    # that exceed 10M (even accounting for chroma-hnswlib format quirks)
    max_el, = struct.unpack_from('<Q', data, 8)
    if ll_size > 100_000_000 or max_el > 10_000_000_000_000_000:
        corrupt.append(seg_id)
        print(f'  CORRUPT: {seg_id} (link_lists={ll_size}B max={max_el:,})')
    else:
        print(f'  ok: {seg_id} (link_lists={ll_size}B max={max_el:,})')

# Write to a temp file for the shell to read
with open('/tmp/corrupt_segs.txt', 'w') as f:
    for s in corrupt:
        f.write(s + '\n')
PYEOF

echo "==> Deleting stale HNSW binaries from corrupt segments..."
while IFS= read -r seg; do
  dir="$PALACE/$seg"
  echo "  Clearing $seg"
  for f in header.bin link_lists.bin data_level0.bin index_metadata.pickle; do
    [ -f "$dir/$f" ] && rm "$dir/$f" && echo "    deleted $f" || true
  done
done < /tmp/corrupt_segs.txt
rm -f /tmp/corrupt_segs.txt

echo "==> Running mempalace repair..."
"$VENV/mempalace" repair

echo "==> Running health check..."
"$VENV/python" /opt/proj/Uncle-J-s-Refinery/mempalace-health.py

echo ""
echo "Done. HNSW rebuilt clean."

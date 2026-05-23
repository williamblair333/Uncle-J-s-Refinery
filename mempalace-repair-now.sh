#!/usr/bin/env bash
# Run immediately after restarting Claude Code (before any mine jobs run).
# Rebuilds corrupted HNSW index from intact SQLite data.
# Safe to re-run; idempotent.
set -euo pipefail

VENV="/opt/proj/Uncle-J-s-Refinery/.venv/bin"
PALACE="$HOME/.mempalace/palace"
SEGS=(
  "3a9d5d2b-2ccd-45c7-9bde-54bd7dc1a784"
  "859be8a7-69ca-4409-81ab-4386a620320c"
)

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

echo "==> Deleting stale HNSW binaries from active segments..."
for seg in "${SEGS[@]}"; do
  dir="$PALACE/$seg"
  for f in header.bin link_lists.bin data_level0.bin index_metadata.pickle; do
    [ -f "$dir/$f" ] && rm "$dir/$f" && echo "  deleted $seg/$f" || true
  done
done

echo "==> Running mempalace repair..."
"$VENV/mempalace" repair

echo "==> Running health check..."
"$VENV/python" /opt/proj/Uncle-J-s-Refinery/mempalace-health.py

echo ""
echo "Done. HNSW will be rebuilt on next mine run (single-threaded, safe)."

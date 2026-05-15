
---
name: mempalace-hnsw-corruption-fix
description: Diagnose and fix MemPalace HNSW index corruption where link_lists.bin grows to hundreds of GB due to chromadb-hnswlib 1.5.x type-confusion in Rust bindings. Use when link_lists.bin is abnormally large, mine crashes with OOM, or header.bin shows astronomical element counts.

---

## When to use

- `~/.mempalace/palace/*/link_lists.bin` is abnormally large (GB+ range)
- `mempalace mine` crashes with OOM or hangs
- `header.bin` shows `max_elements` or `cur_element_count` in the trillions (C++ pointer values written where integers should be)
- Mine log shows repeated runs each making the file larger
- SQLite drawer count diverges from HNSW `cur_element_count`

## Root cause

chromadb-hnswlib 1.5.x has a type-confusion bug in its Rust bindings: `element_levels_[i]` is written as float but read as int32. The `updatePoint` path (called on every upsert of an existing item) triggers it. This produces ~1 billion as link list sizes per node, so hnswlib treats each node as having a ~1 GB link list. Every subsequent mine run reads the corrupt header and serializes back equally-corrupted output, compounding the damage.

## Step 1 — Stop active processes immediately

# Find and kill any stuck mine processes
ps aux | grep mempalace
kill <pid>

# Remove stale lockfiles
ls ~/.mempalace/palace/*/locks/
rm ~/.mempalace/palace/*/locks/*.lock

## Step 2 — Assess damage

# Check link_lists.bin size
du -sh ~/.mempalace/palace/*/link_lists.bin

# Check header values (Python)
python3 - <<'EOF'
import struct, pathlib
p = pathlib.Path("~/.mempalace/palace").expanduser()
for f in p.glob("*/header.bin"):
    data = f.read_bytes()
    # hnswlib header: offset_level0_=8, max_elements_=16, cur_element_count_=24
    max_el, cur_el = struct.unpack_from('<qq', data, 16)
    print(f"{f.parent.name}: max={max_el:,}  cur={cur_el:,}")
EOF

# Compare SQLite vs HNSW counts
python3 - <<'EOF'
import sqlite3, pathlib
p = pathlib.Path("~/.mempalace").expanduser()
for db in p.glob("palace/*/chroma.sqlite3"):
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM embedding_fulltext_search_content").fetchone()[0]
    print(f"{db.parent.name}: SQLite={count:,}")
    conn.close()
EOF

Sane header values: `max_elements` ≈ 10K–100K range. Trillion-scale values confirm corruption.

## Step 3 — Check source text recoverability

Before deleting any HNSW files, confirm source text is in SQLite (so you can re-mine):

python3 - <<'EOF'
import sqlite3, pathlib
p = pathlib.Path("~/.mempalace").expanduser()
for db in p.glob("palace/*/chroma.sqlite3"):
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM embedding_fulltext_search_content").fetchone()[0]
    print(f"{db.parent.name}: {count:,} recoverable rows")
    conn.close()
EOF

**Note:** embedding vectors live only in HNSW binary files (`data_level0.bin`). Deleting HNSW means losing vectors — but source text in `embedding_fulltext_search_content` lets you re-embed from scratch.

## Step 4 — Delete corrupt HNSW and rebuild

# Delete only HNSW files (not SQLite)
rm ~/.mempalace/palace/<segment>/header.bin
rm ~/.mempalace/palace/<segment>/link_lists.bin
rm ~/.mempalace/palace/<segment>/data_level0.bin
rm -f ~/.mempalace/palace/<segment>/index_metadata.pickle

# Trigger rebuild via mempalace repair
mempalace repair

## Step 5 — Verify rebuild is sane

du -sh ~/.mempalace/palace/*/link_lists.bin   # expect KB, not GB

python3 - <<'EOF'
import struct, pathlib
p = pathlib.Path("~/.mempalace/palace").expanduser()
for f in p.glob("*/header.bin"):
    data = f.read_bytes()
    max_el, cur_el = struct.unpack_from('<qq', data, 16)
    print(f"{f.parent.name}: max={max_el:,}  cur={cur_el:,}")
EOF

**Known caveat (chromadb 1.5.8):** Even a fresh rebuild may show `cur_element_count = N × 2^32` in the header due to the same type-confusion bug. The files stay small until `updatePoint` is called (i.e., until a second mine run adds items that already exist). The explosion happens on the second mine, not the first.

## Step 6 — Pin chromadb version to avoid recurrence

The fix is to downgrade or pin chromadb-hnswlib to a version before the Rust binding regression:

pip install "chromadb-hnswlib==0.7.6"  # last known-good version
# or pin in pyproject.toml:
# "chromadb-hnswlib==0.7.6"

After pinning, re-run repair and verify header values are sane after a mine run that includes updates to existing items.

## Step 7 — Set up a watch

# Add to cron or monitoring — alert if link_lists.bin exceeds 100 MB
watch -n 60 'du -sh ~/.mempalace/palace/*/link_lists.bin'

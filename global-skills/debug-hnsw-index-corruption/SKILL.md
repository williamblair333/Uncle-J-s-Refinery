---
name: debug-hnsw-index-corruption
description: Diagnose and fix corrupted HNSW vector index files in chromadb/MemPalace — covers runaway link_lists.bin growth, garbage header values, and type-confusion in hnswlib Rust bindings
---

## When to use

Invoke when:
- `link_lists.bin` in a chromadb/MemPalace segment is abnormally large (GBs instead of MBs)
- Mine or upsert operations slow down or crash after running
- chromadb raises memory allocation errors or segfaults
- `cur_element_count` in the HNSW header doesn't match the SQLite row count

## Phase 1 — Evidence gathering (run in parallel)

# Check binary file sizes across all segments
find ~/.mempalace/palace -name "*.bin" | xargs ls -lh

# Check SQLite row count vs HNSW header element count
sqlite3 ~/.mempalace/palace/<wing>/<room>/chroma.sqlite3 \
  "SELECT COUNT(*) FROM embeddings WHERE segment_id='<uuid>';"

# Read HNSW header (first 40 bytes)
python3 - <<'EOF'
import struct, sys
with open("/path/to/header.bin","rb") as f:
    data = f.read(40)
fields = struct.unpack_from("<QQQQQQ", data)
names = ["offset_level0_","max_elements_","cur_element_count","size_data_per_element","label_offset_","offsetData_"]
for n,v in zip(names, fields): print(f"{n}: {v:,}")
EOF

# Check length.bin for garbage values
python3 - <<'EOF'
import struct
with open("/path/to/length.bin","rb") as f:
    data = f.read(32)
vals = struct.unpack_from("<" + "I"*(len(data)//4), data)
print("First link-list sizes:", vals)
EOF

**Red flags:**
- `max_elements` > 1 trillion → pointer value written as int (type confusion)
- `cur_element_count` mismatches SQLite count → HNSW out of sync with store
- Link-list sizes ~1,000,000,000 bytes each → float-as-int32 read (hnswlib 1.5.x bug)
- `link_lists.bin` growing during mine runs → save path writing with corrupted params

## Phase 2 — Containment

# Stop all mine/upsert processes immediately before more damage
pkill -f "mempalace mine" || true
pkill -f "chroma"         || true

# Remove stale lockfiles if mine died mid-run
rm -f ~/.mempalace/mine.lock ~/.mempalace/mine_*.lock

## Phase 3 — Root cause identification

| Symptom | Root cause |
|---|---|
| Header `max_elements` = pointer value | C++ pointer written to wrong field (chromadb-hnswlib 1.5.x Rust binding type confusion) |
| `dimensionality: None` in `index_metadata.pickle` | Rebuild not passing correct dim to hnswlib; corrupt header propagated |
| `element_levels_[i]` produces ~1B link-list sizes | Float bit pattern misread as int32 in `updatePoint` path |
| Corruption recurs after rebuild | Bug is in the write path itself, not just stale data |

## Phase 4 — Fix procedure

# 1. Delete HNSW binary files (NOT the SQLite store — metadata is safe)
rm /path/to/segment/{header,length,data_level0,link_lists}.bin

# 2. Trigger minimal rebuild (chromadb recreates from SQLite on next access)
python3 -c "import chromadb; c = chromadb.PersistentClient('/path/to/palace'); c.get_collection('<name>').count()"

# 3. Immediately verify header after rebuild — before running mine
python3 - <<'EOF'
import struct
with open("/path/to/header.bin","rb") as f:
    d = f.read(24)
me, ce = struct.unpack_from("<QQ", d, 8)
print(f"max_elements={me:,}  cur_element_count={ce:,}")
assert me < 10_000_000, f"still corrupted: max_elements={me}"
EOF

# 4. Check link_lists.bin size stays small after rebuild
ls -lh /path/to/link_lists.bin   # should be KBs not GBs

## Phase 5 — Long-term fix

- Downgrade `chromadb-hnswlib` away from 1.5.x: `pip install chromadb-hnswlib==0.7.6`
- Or pin chromadb to a version that doesn't pull hnswlib 1.5.x
- Add concurrency lockfiles to all mine wrapper scripts to prevent parallel runs
- Monitor `link_lists.bin` size after each mine run as a canary

## Key invariants

- Source text is recoverable from `embedding_fulltext_search_content` in SQLite — data is never truly lost
- Embedding vectors live **only** in `data_level0.bin` — losing HNSW means re-embedding from source
- The `updatePoint` path (called on every upsert of an existing item) is the trigger — first mine run after corruption produces modest growth; subsequent runs explode it

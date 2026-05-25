---
name: mempalace-hnsw-corruption-fix
description: Diagnose and fix MemPalace HNSW index corruption where link_lists.bin grows to hundreds of GB due to chromadb-hnswlib 1.5.x type-confusion in Rust bindings. Use when link_lists.bin is abnormally large, mine crashes with OOM, or header.bin shows astronomical element counts.
---

## When to use

- `~/.mempalace/palace/*/link_lists.bin` is abnormally large (GB+ range)
- `mempalace mine` crashes with OOM or hangs
- `header.bin` shows `max_elements` or `cur_element_count` in the trillions
- Mine log shows repeated runs each making the file larger
- SQLite drawer count diverges from HNSW `cur_element_count`

## Root cause

chromadb 1.5.x defaults to `RustBindingsAPI`. The Rust HNSW binding has a
type-confusion bug: `element_levels_[i]` is written as float but read as int32.
Every `updatePoint` call (upsert of an existing item) triggers it, producing
~1 billion link-list sizes per node.

**Critical:** Pinning `chromadb==1.5.8` is NOT sufficient. Without `chroma-hnswlib`
installed, chromadb has no Python hnswlib fallback and always uses the broken Rust
path. The repair itself calls `updatePoint` on existing items, immediately
re-corrupting the fresh HNSW files.

**Full fix requires both:**
1. `chroma-hnswlib==0.7.6` installed (provides the `hnswlib` Python module)
2. `CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI` set in every entry point

## Step 1 — Install the Python hnswlib package

```bash
# In the mempalace venv:
uv pip install "chroma-hnswlib==0.7.6"

# Verify it's present:
python3 -c "import hnswlib; print(hnswlib.__file__)"
```

Also add to `pyproject.toml` under `[tool.uv.override-dependencies]` and
`[project.dependencies]` so `uv sync` keeps it.

## Step 2 — Set CHROMA_API_IMPL in ALL entry points

Every process that touches chromadb must export:

```bash
export CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI
```

Patch **all** of the following:
- MCP start script (`mempalace-mcp-start.sh` or equivalent)
- Mine script (`mempalace-mine-convos.sh` or equivalent)
- Repair script (`mempalace-repair-now.sh`)
- Crontab — add as a top-level variable before all entries:
  `CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI`
- Stop hook in `settings.json` — route via the patched script, not direct `mempalace mine`

## Step 3 — Check for active mine processes and wait

```bash
ps aux | grep mempalace | grep -v grep
```

**Wait for them to finish** — do NOT kill a running mine. Deleting HNSW while
a mine is active means the mine writes fresh corrupt files on top of your repair.

```bash
# Monitor until process exits:
watch -n 5 'ps aux | grep mempalace | grep -v grep'
```

Once all mine processes have exited, also remove stale lockfiles:

```bash
rm -f ~/.mempalace/palace/*/locks/*.lock
```

## Step 4 — Assess damage

```bash
# Primary corruption indicator: link_lists.bin > 100 MB
du -sh ~/.mempalace/palace/*/link_lists.bin

# Check header values (correct Python hnswlib offsets)
python3 - <<'EOF'
import struct, pathlib
p = pathlib.Path("~/.mempalace/palace").expanduser()
for f in p.glob("*/header.bin"):
    data = f.read_bytes()
    # Python hnswlib format: max_elements at offset 8, cur_element_count at offset 16
    max_el = struct.unpack_from('<q', data, 8)[0]
    cur_el = struct.unpack_from('<q', data, 16)[0]
    link_sz = (f.parent / "link_lists.bin").stat().st_size
    print(f"{f.parent.name}: max={max_el:,} cur={cur_el:,} link_lists={link_sz/1e6:.1f}MB")
EOF
```

Sane values: `max_elements` ≈ 10K–500K; `link_lists.bin` ≤ a few MB.
Corruption signature: `cur_element_count` ≈ 652 billion; `link_lists.bin` in GB.

## Step 5 — Dynamically detect corrupt segments

Do not hardcode segment IDs. Detect dynamically:

```bash
python3 - <<'EOF'
import pathlib, sqlite3
palace = pathlib.Path("~/.mempalace/palace").expanduser()
threshold = 100 * 1024 * 1024  # 100 MB

# Find corrupt segments
corrupt = {ll.parent.name for ll in palace.glob("*/link_lists.bin")
           if ll.stat().st_size > threshold}

# Cross-reference against active segments in SQLite
db = pathlib.Path("~/.mempalace/chroma.sqlite3").expanduser()
conn = sqlite3.connect(db)
active = {r[0] for r in conn.execute("SELECT id FROM segments")}
conn.close()

for seg in corrupt & active:
    print(f"CORRUPT ACTIVE: {seg}")
for seg in corrupt - active:
    print(f"CORRUPT ORPHAN (skip): {seg}")
EOF
```

Only repair segments that are both corrupt AND active.

## Step 6 — Check source text recoverability

```bash
python3 - <<'EOF'
import sqlite3, pathlib
p = pathlib.Path("~/.mempalace").expanduser()
for db in p.glob("palace/*/chroma.sqlite3"):
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM embedding_fulltext_search_content").fetchone()[0]
    print(f"{db.parent.name}: {count:,} recoverable rows")
    conn.close()
EOF
```

Embedding vectors live only in HNSW binary files. Deleting them loses vectors,
but source text in `embedding_fulltext_search_content` lets you re-embed from scratch.

## Step 7 — Delete corrupt HNSW and rebuild

```bash
# Use from-sqlite mode — reads directly from chroma.sqlite3, never opens
# the corrupt HNSW files (avoids SIGBUS from corrupt max_el values).
# --archive-existing renames the current palace to palace.pre-rebuild-<ts>
# so it can be restored if needed.
CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI \
  mempalace repair --mode from-sqlite --yes --archive-existing
```

> **Do NOT use `mempalace repair --yes` (legacy mode)** — it opens the
> chromadb client against the corrupt palace, hits the Rust SIGBUS, and
> writes NEW corrupt headers to additional segments, making things worse.
> Manual segment deletion before repair is also unnecessary with this mode.

## Step 8 — Verify the fix holds

```bash
# Run a mine pass, then check sizes again
CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI mempalace mine

du -sh ~/.mempalace/palace/*/link_lists.bin   # expect KB–low MB, stable
```

If `link_lists.bin` grows again on the second mine run, Step 1 or Step 2 is
incomplete — a process is still reaching the Rust path.

## Health check threshold

Use `link_lists.bin > 100 MB` as the corruption indicator. Header-based checks
are unreliable because the Python hnswlib format stores larger uint64 values
than the Rust format, causing false positives at lower thresholds.

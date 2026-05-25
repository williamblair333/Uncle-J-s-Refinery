---
name: mempalace-repair-mine-interference
description: Diagnose and resolve MemPalace repair failures caused by active mine jobs holding the SQLite write lock, an install script respawning miners, or FTS5 full-text index corruption discovered alongside HNSW corruption. Use when `mempalace repair` hangs, errors with "database is locked", or when FTS5 queries return nothing after HNSW is fixed.
---

## When to use

Invoke after `mempalace-hnsw-corruption-fix` Step 4 (delete corrupt HNSW binaries) when repair is blocked by a lock error, or when FTS5 queries stop returning results after HNSW repair.

## Step 1 — Detect the lock

fuser ~/.mempalace/palace/chroma.sqlite3
lsof ~/.mempalace/palace/chroma.sqlite3

If processes appear, check if they are mine jobs:

ps aux | grep mempalace

## Step 2 — Assess: stuck or legitimately working?

Check CPU usage. If miners are consuming CPU (>10%), they are actively working, not stuck. But each write risks re-triggering the `updatePoint` corruption bug before the version pin is applied. Safe to kill — SQLite is ACID.

## Step 3 — Find and stop the spawning source

An install script or cron may be restarting miners. Check before killing:

crontab -l | grep mempalace
systemctl list-units | grep mempalace
ps aux | grep -E "(install|mine|mempalace)" | grep -v grep

Stop the spawning source first, then kill the mine processes:

# Kill all mine jobs (SIGTERM is clean — SQLite rolls back in-flight transactions)
pkill -f "mempalace mine"

Wait ~5 seconds, then verify only the MCP server remains:

ps aux | grep mempalace | grep -v grep

## Step 4 — Run repair

```bash
# Use from-sqlite mode to avoid SIGBUS from corrupt HNSW headers
CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI \
  mempalace repair --mode from-sqlite --yes --archive-existing
```

## Step 5 — Detect FTS5 corruption

If repair succeeds but keyword search returns nothing, the FTS5 full-text index is corrupt (separate from HNSW). Check:

sqlite3 ~/.mempalace/palace/chroma.sqlite3 \
  "SELECT count(*) FROM embedding_fulltext_search_content;"

If this returns rows but BM25 search is empty, FTS5 is corrupt. The underlying content table is intact — rebuild in place:

sqlite3 ~/.mempalace/palace/chroma.sqlite3 \
  "INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('rebuild');"

This rebuilds the FTS5 index from the content table. On 474K rows, expect 2–5 minutes. The MCP server can remain open during the rebuild.

## Step 6 — Apply the version pin (critical)

Without this, every subsequent mine run will re-corrupt HNSW. See `mempalace-hnsw-corruption-fix` Step 6:

uv pip install "chromadb-hnswlib==0.7.6"

Verify:
uv pip show chromadb-hnswlib | grep Version

## Step 7 — Verify recovery

mempalace health
# Expect: HNSW count matches SQLite count (~474K), FTS5 healthy

## Key facts

- `link_lists.bin = 0 bytes` with astronomical header count (`cur_element_count > 7T`) is the same corruption as a multi-GB file — same root cause, same fix.
- `.corrupt-` and `.drift-` backup accumulation across multiple dates means the version pin was never applied and each mine run re-triggered the bug.
- Killing mine jobs is safe: SQLite ACID guarantees rollback of in-flight transactions.
- The health check's corruption detector skips when `max_elements = 0`, so it will not catch this pattern — manual verification required after repair.

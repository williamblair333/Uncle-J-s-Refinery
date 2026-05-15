---
name: mempalace-hnsw-corruption-fix
description: Diagnose and fix MemPalace HNSW index corruption where link_lists.bin grows to hundreds of GB due to chromadb-hnswlib 1.5.x type-confusion in Rust bindings. Use when link_lists.bin is abnormally large, mine crashes with OOM, or header.bin shows astronomical element counts.
---

## When to use

- `link_lists.bin` is larger than ~100 MB (healthy: single-digit MB)
- Mine runs complete but HNSW grows unbounded after each run
- chromadb segfaults or OOMs loading the index
- `cur_element_count` in header.bin doesn't match SQLite record count

## Root cause

chromadb-hnswlib 1.5.x has a Rust type-confusion bug: `element_levels_[i]` is written as float but read as int32, producing ~1 billion as link-list sizes per node. The `updatePoint` path (called on every upsert of an existing item) triggers it. Rebuilds re-create the corrupt header if `dimensionality` is `None` in `index_metadata.pickle`.

## Diagnostic steps

# 1. Check link_lists.bin size (healthy = single-digit MB)
ls -lh ~/.mempalace/palace/*/link_lists.bin

# 2. Read header.bin — look for astronomical max_elements / cur_element_count
python3 - <<'EOF'
import struct, pathlib
for p in pathlib.Path("~/.mempalace/palace").expanduser().glob("*/header.bin"):
    with open(p, "rb") as f:
        data = f.read(32)
    if len(data) >= 24:
        offset_size, max_elems, cur_elems = struct.unpack_from("<QQQ", data, 0)
        print(f"{p.parent.name}: max={max_elems:,} cur={cur_elems:,}")
EOF

# 3. Compare HNSW element count vs SQLite
sqlite3 ~/.mempalace/palace/<wing>/store.db "SELECT COUNT(*) FROM embeddings;"

If `max_elements` or `cur_element_count` are in the trillions — corruption confirmed.

## Fix procedure

# 1. Kill mine processes and clear stale locks
pkill -f "mempalace mine" || true
rm -f ~/.mempalace/palace/*/mine.lock
rm -f ~/.mempalace/mine.lock

# 2. Stop mine cron (prevents re-corruption during fix)
crontab -l | grep -v "mempalace mine" | crontab -

# 3. Delete corrupted HNSW files (vectors live here — source text is in SQLite)
rm -f ~/.mempalace/palace/<wing>/data_level0.bin
rm -f ~/.mempalace/palace/<wing>/link_lists.bin
rm -f ~/.mempalace/palace/<wing>/header.bin
rm -f ~/.mempalace/palace/<wing>/length.bin

# 4. Trigger minimal rebuild via mempalace CLI or MCP
# Via MCP: call mempalace_reconnect or mempalace_sync
# Via CLI: mempalace rebuild --wing <wing>

# 5. Immediately check header values after rebuild
python3 - <<'EOF'
import struct, pathlib
p = pathlib.Path("~/.mempalace/palace/<wing>/header.bin").expanduser()
with open(p, "rb") as f:
    data = f.read(32)
offset_size, max_elems, cur_elems = struct.unpack_from("<QQQ", data, 0)
print(f"max={max_elems:,} cur={cur_elems:,}")  # expect: sane numbers matching SQLite count
EOF

## After fix

- `link_lists.bin` should be kilobytes, not gigabytes
- `cur_element_count` in header.bin should match SQLite `COUNT(*)`
- Check `index_metadata.pickle` — `dimensionality` must be `384` (not `None`)
- Re-enable mine cron only after confirming header is stable
- Pin chromadb-hnswlib below 1.5.x or monitor for upstream fix before upgrading

## Recurrence monitoring

Add to post-mine health check:

size=$(stat -c%s ~/.mempalace/palace/*/link_lists.bin 2>/dev/null | sort -n | tail -1)
[ "${size:-0}" -gt 104857600 ] && echo "WARN: link_lists.bin > 100MB — check for HNSW corruption"

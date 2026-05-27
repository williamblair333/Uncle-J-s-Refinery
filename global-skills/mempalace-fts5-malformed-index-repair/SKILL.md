---
name: mempalace-fts5-malformed-index-repair
description: Repair a MemPalace SQLite FTS5 malformed inverted index reported by healthcheck as CRIT. Distinct from HNSW corruption (link_lists.bin) and HNSW 0-elements after reboot.
metadata:
  type: project
---

## When to use

HEALTHCHECK reports `mempalace-sqlite` as **CRIT** with "malformed inverted index" or an FTS5 error.
This is SQLite full-text search table corruption — different from:
- HNSW segment corruption → use `mempalace-hnsw-corruption-fix`
- HNSW 0-elements after reboot → use `mempalace-boot-repair-always-runs`

## Steps

1. **Confirm the failure** — healthcheck output names `mempalace-sqlite` with FTS5/inverted-index language.

2. **Clear any stale mine lock** — if a stale lock is reported alongside the corruption, clear it first so the repair can acquire the DB.

3. **Trigger FTS5 rebuild** — the DB is large (1–2 GB); expect several minutes, DB will be locked:
   ```bash
   sqlite3 ~/.mempalace/palace.db \
     "INSERT INTO sections_fts(sections_fts) VALUES('rebuild');"
   ```

4. **Run parallel work while waiting** — use rebuild time productively (jcodemunch digest, catch-up pull). Do not poll; the sqlite3 process will exit when done.

5. **Verify after completion**:
   ```bash
   sqlite3 ~/.mempalace/palace.db "PRAGMA integrity_check;"
   ```
   Then call `mempalace_status` to confirm embedding count is intact (expect ~290K+ embeddings).

6. **Re-run healthcheck** — confirm `mempalace-sqlite` is OK before resuming work.

## Notes

- FTS5 corruption is independent of HNSW health — check both separately.
- FTS5 table name may vary; inspect schema if `sections_fts` doesn't exist.
- If the DB is already locked on arrival, wait for the existing process rather than killing it.
- A stale mine lock often co-occurs with FTS5 corruption after an unclean shutdown — address both.

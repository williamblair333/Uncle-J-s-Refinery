# TurboVecDB Parallel Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run turbovecdb in parallel against the live 296K-drawer MemPalace palace, logging build time, query p50/p95 latency, and recall@10 vs ChromaDB weekly for weeks-long community-reportable evaluation.

**Architecture:** Four scripts: (1) one-time migration from ChromaDB → turbovecdb, (2) nightly incremental sync after the 3am mine, (3) weekly benchmark runner comparing both backends on the same query vectors, (4) weekly report poster to GitHub discussion. turbovecdb lives at `~/.turbovecdb-eval/` — completely separate from `~/.mempalace/`. ChromaDB stays the production backend throughout.

**Tech Stack:** Python 3.11 (project venv), `chromadb` (already in venv), `turbovecdb` (installed from patched fork `williamblair333/turbovecdb@fix/security-findings`), `numpy`, `gh` CLI for report posting.

---

## Known context

- **ChromaDB palace**: `~/.mempalace/palace/`, 296,126 drawers in `mempalace_drawers` (384-dim float32) + 274 in `mempalace_closets`
- **Project venv**: `/opt/proj/Uncle-J-s-Refinery/.venv/bin/python3` — has `chromadb`, needs `turbovecdb`
- **Vector source**: ChromaDB Python API via `PersistentClient` (reads both compacted HNSW + WAL queue)
- **Metadata shape**: `{'wing': str, 'room': str, 'hall': str, 'type': str, 'topic': str, 'date': str, 'filed_at': str, 'chunk_index': int, ...}` — all JSON-scalar, compatible with turbovecdb filters
- **ID shape**: `'drawer_uncle_j_s_refinery_general_abc123'`, `'diary_wing_...'` — all alphanumeric+underscore, pass `_SAFE_NAME` in our patched turbovecdb (max 128 chars — must truncate if over)
- **Benchmark approach**: sample 200 drawer vectors directly from ChromaDB, use them as query vectors against both backends (no re-embedding needed), measure overlap of top-10 IDs as recall@10
- **Recall@10 definition**: `|top10_chroma ∩ top10_turbovec| / 10`
- **State files**: `state/turbovecdb-sync-state.json`, `state/turbovecdb-eval.jsonl`
- **Discussion to post to**: `MemPalace/mempalace` discussion `#1668`, comment `DC_kwDOR5_Rks4BBi85` (our existing comment) — use `updateDiscussionComment` to append weekly report

---

## File map

| File | Action | Responsibility |
|------|--------|---------------|
| `scripts/turbovecdb-migrate.py` | Create | One-time: read all ChromaDB drawers, write to turbovecdb in batches |
| `scripts/turbovecdb-sync.py` | Create | Incremental: find IDs in ChromaDB not yet in turbovecdb, load them |
| `scripts/turbovecdb-benchmark.py` | Create | Sample query vectors, query both backends, log p50/p95 + recall@10 |
| `scripts/turbovecdb-report.sh` | Create | Aggregate eval log, build markdown table, post to GitHub discussion |
| `scripts/turbovecdb-install.sh` | Create | Install turbovecdb into project venv, register crons |
| `state/turbovecdb-sync-state.json` | Created at runtime | Tracks last sync count for incremental sync |
| `state/turbovecdb-eval.jsonl` | Created at runtime | Append-only benchmark log (one JSON line per run) |

---

## Task 1: Install patched turbovecdb into project venv

**Files:**
- Create: `scripts/turbovecdb-install.sh`

- [ ] **Step 1: Write install script**

```bash
cat > /opt/proj/Uncle-J-s-Refinery/scripts/turbovecdb-install.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
VENV=/opt/proj/Uncle-J-s-Refinery/.venv
FORK="git+https://github.com/williamblair333/turbovecdb.git@fix/security-findings"

echo "Installing turbovecdb from patched fork..."
"$VENV/bin/pip" install --quiet "$FORK"
"$VENV/bin/python3" -c "import turbovecdb; print('turbovecdb', turbovecdb.__version__, 'ok')"

# Register crons (idempotent: remove old, add new)
PROJ=/opt/proj/Uncle-J-s-Refinery

crontab -l 2>/dev/null | grep -v "turbovecdb-sync\|turbovecdb-benchmark\|turbovecdb-report" | \
  { cat; \
    echo "30 3 * * * cd $PROJ && .venv/bin/python3 scripts/turbovecdb-sync.py >> state/turbovecdb-sync.log 2>&1"; \
    echo "0 6 * * 0 cd $PROJ && bash scripts/turbovecdb-report.sh >> state/turbovecdb-report.log 2>&1"; \
  } | crontab -

echo "Crons registered:"
crontab -l | grep turbovecdb
EOF
chmod +x /opt/proj/Uncle-J-s-Refinery/scripts/turbovecdb-install.sh
```

- [ ] **Step 2: Run it**

```bash
bash /opt/proj/Uncle-J-s-Refinery/scripts/turbovecdb-install.sh
```

Expected: `turbovecdb 0.1.0 ok` + two cron lines printed.

- [ ] **Step 3: Verify**

```bash
/opt/proj/Uncle-J-s-Refinery/.venv/bin/python3 -c "
import turbovecdb
db = turbovecdb.connect('/tmp/tvdb-test')
col = db.collection('test', dim=8, create=True)
import numpy as np
col.add(ids=['a'], documents=['hello'], vectors=[np.random.randn(8).tolist()])
print('count:', col.count())
db.close()
import shutil; shutil.rmtree('/tmp/tvdb-test')
print('turbovecdb install verified')
"
```

Expected: `count: 1` + `turbovecdb install verified`

- [ ] **Step 4: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add scripts/turbovecdb-install.sh
git commit -m "feat: turbovecdb-install.sh — install patched fork + register crons"
```

---

## Task 2: Initial migration script

**Files:**
- Create: `scripts/turbovecdb-migrate.py`

The migration reads all drawers from ChromaDB via `PersistentClient` in batches of 1000. ChromaDB IDs can be up to 128+ chars — turbovecdb's `_SAFE_NAME` allows up to 128 chars of `[A-Za-z0-9_-]`. IDs like `drawer_uncle_j_s_refinery_...` contain only safe chars but may exceed 128 — we sha256-truncate the suffix if needed.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""One-time migration: ChromaDB palace → turbovecdb at ~/.turbovecdb-eval/"""

import hashlib
import json
import os
import sys
import time

import chromadb
import numpy as np
import turbovecdb

PALACE = os.path.expanduser("~/.mempalace/palace")
TVDB_PATH = os.path.expanduser("~/.turbovecdb-eval")
BATCH = 1000
STATE_FILE = "/opt/proj/Uncle-J-s-Refinery/state/turbovecdb-sync-state.json"
COLLECTIONS = ["mempalace_drawers", "mempalace_closets"]


def safe_id(raw_id: str) -> str:
    """turbovecdb requires [A-Za-z0-9_-]{1,128}. Truncate+hash suffix if over."""
    clean = raw_id.replace(":", "_").replace("/", "_").replace(".", "_")
    if len(clean) <= 128:
        return clean
    suffix = hashlib.sha256(raw_id.encode()).hexdigest()[:8]
    return clean[:119] + "_" + suffix


def migrate_collection(chroma_client, tvdb, name):
    chroma_col = chroma_client.get_collection(name)
    total = chroma_col.count()
    print(f"\n{name}: {total} drawers", flush=True)

    try:
        tvdb_col = tvdb.collection(name, dim=384, create=False)
        existing = tvdb_col.count()
        print(f"  turbovecdb already has {existing}; resuming from offset {existing}")
        start_offset = existing
    except Exception:
        tvdb_col = tvdb.collection(name, dim=384, create=True)
        start_offset = 0

    migrated = 0
    t0 = time.monotonic()

    for offset in range(start_offset, total, BATCH):
        batch = chroma_col.get(
            limit=BATCH,
            offset=offset,
            include=["embeddings", "documents", "metadatas"],
        )
        ids = [safe_id(i) for i in batch["ids"]]
        docs = batch["documents"] or [""] * len(ids)
        metas = batch["metadatas"] or [{}] * len(ids)
        vecs = [np.array(v, dtype=np.float32).tolist() for v in batch["embeddings"]]

        # Sanitize metadata values to JSON-scalar types only
        clean_metas = []
        for m in metas:
            clean_metas.append(
                {k: v for k, v in m.items() if isinstance(v, (str, int, float, bool))}
            )

        tvdb_col.add(ids=ids, documents=docs, metadatas=clean_metas, vectors=vecs)
        migrated += len(ids)

        elapsed = time.monotonic() - t0
        rate = migrated / elapsed if elapsed > 0 else 0
        eta = (total - start_offset - migrated) / rate if rate > 0 else 0
        print(
            f"  {migrated + start_offset}/{total} ({rate:.0f}/s, ETA {eta:.0f}s)",
            end="\r",
            flush=True,
        )

    tvdb_col.flush()
    elapsed = time.monotonic() - t0
    print(f"\n  done: {migrated} migrated in {elapsed:.1f}s ({migrated/elapsed:.0f}/s)")
    return migrated, elapsed


def main():
    os.makedirs(TVDB_PATH, exist_ok=True)
    chroma = chromadb.PersistentClient(path=PALACE)
    tvdb = turbovecdb.connect(TVDB_PATH)

    results = {}
    for name in COLLECTIONS:
        n, t = migrate_collection(chroma, tvdb, name)
        results[name] = {"count": n, "elapsed_s": round(t, 1)}

    tvdb.close()

    state = {
        "last_sync_counts": {
            name: chromadb.PersistentClient(path=PALACE).get_collection(name).count()
            for name in COLLECTIONS
        },
        "migration_complete": True,
        "migrated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    print(f"\nMigration complete. State written to {STATE_FILE}")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
```

Save to `/opt/proj/Uncle-J-s-Refinery/scripts/turbovecdb-migrate.py`.

- [ ] **Step 2: Dry-run on 100 rows to verify**

```bash
cd /opt/proj/Uncle-J-s-Refinery
# Quick smoke test: migrate only first 100 to /tmp
CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI \
  .venv/bin/python3 - << 'EOF'
import chromadb, turbovecdb, numpy as np, os, shutil

PALACE = os.path.expanduser("~/.mempalace/palace")
TEST_PATH = "/tmp/tvdb-smoke"
shutil.rmtree(TEST_PATH, ignore_errors=True)

chroma = chromadb.PersistentClient(path=PALACE)
col = chroma.get_collection("mempalace_drawers")
batch = col.get(limit=100, offset=0, include=["embeddings","documents","metadatas"])

tvdb = turbovecdb.connect(TEST_PATH)
tc = tvdb.collection("mempalace_drawers", dim=384, create=True)
tc.add(
    ids=[i[:128] for i in batch["ids"]],
    documents=batch["documents"],
    metadatas=[{k:v for k,v in m.items() if isinstance(v,(str,int,float,bool))} for m in batch["metadatas"]],
    vectors=[np.array(v,dtype=np.float32).tolist() for v in batch["embeddings"]],
)
tc.flush()
print("count:", tc.count())
r = tc.query(vector=batch["embeddings"][0], k=3)
print("query top-3 ids:", r.ids[:3])
tvdb.close()
shutil.rmtree(TEST_PATH)
print("smoke test passed")
EOF
```

Expected: `count: 100`, 3 IDs printed, `smoke test passed`.

- [ ] **Step 3: Run full migration (will take ~10–30 min at 296K rows)**

```bash
cd /opt/proj/Uncle-J-s-Refinery
CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI \
  .venv/bin/python3 scripts/turbovecdb-migrate.py 2>&1 | tee state/turbovecdb-migrate.log
```

Expected: progress lines, then `Migration complete. State written to state/turbovecdb-sync-state.json`.

- [ ] **Step 4: Verify row counts match**

```bash
.venv/bin/python3 - << 'EOF'
import turbovecdb, chromadb, os
chroma = chromadb.PersistentClient(path=os.path.expanduser("~/.mempalace/palace"))
tvdb = turbovecdb.connect(os.path.expanduser("~/.turbovecdb-eval"))
for name in ["mempalace_drawers", "mempalace_closets"]:
    c_count = chroma.get_collection(name).count()
    t_count = tvdb.collection(name, create=False).count()
    status = "OK" if abs(c_count - t_count) < 10 else "MISMATCH"
    print(f"{name}: chroma={c_count} turbovec={t_count} [{status}]")
tvdb.close()
EOF
```

Expected: both lines show `[OK]` (within 10 = WAL lag tolerance).

- [ ] **Step 5: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add scripts/turbovecdb-migrate.py state/turbovecdb-migrate.log state/turbovecdb-sync-state.json
git commit -m "feat: turbovecdb-migrate.py — one-time ChromaDB → turbovecdb migration"
```

---

## Task 3: Nightly sync script

**Files:**
- Create: `scripts/turbovecdb-sync.py`

Runs at 3:30am (after the 3am mine). Reads all IDs from ChromaDB, gets all IDs from turbovecdb, diffs them, loads missing ones. Fast for small deltas (nightly mine adds ~few hundred rows).

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Incremental sync: load new ChromaDB drawers into turbovecdb."""

import json
import os
import time

import chromadb
import numpy as np
import turbovecdb

PALACE = os.path.expanduser("~/.mempalace/palace")
TVDB_PATH = os.path.expanduser("~/.turbovecdb-eval")
STATE_FILE = "/opt/proj/Uncle-J-s-Refinery/state/turbovecdb-sync-state.json"
COLLECTIONS = ["mempalace_drawers", "mempalace_closets"]
BATCH = 500


def safe_id(raw_id: str) -> str:
    import hashlib
    clean = raw_id.replace(":", "_").replace("/", "_").replace(".", "_")
    if len(clean) <= 128:
        return clean
    suffix = hashlib.sha256(raw_id.encode()).hexdigest()[:8]
    return clean[:119] + "_" + suffix


def sync_collection(chroma_client, tvdb, name):
    chroma_col = chroma_client.get_collection(name)
    tvdb_col = tvdb.collection(name, dim=384, create=True)

    # Get all ChromaDB IDs
    all_chroma = chroma_col.get(include=[])
    chroma_ids = set(all_chroma["ids"])

    # Get all turbovecdb IDs
    tvdb_ids = set(tvdb_col.get(include=[]).ids)

    # Map back: safe_id(chroma_id) → chroma_id
    safe_to_raw = {safe_id(i): i for i in chroma_ids}
    missing_safe = set(safe_to_raw) - tvdb_ids
    missing_raw = [safe_to_raw[s] for s in missing_safe]

    if not missing_raw:
        print(f"  {name}: in sync ({len(chroma_ids)} drawers)")
        return 0

    print(f"  {name}: {len(missing_raw)} new drawers to sync")
    loaded = 0
    for i in range(0, len(missing_raw), BATCH):
        chunk_ids = missing_raw[i:i + BATCH]
        batch = chroma_col.get(
            ids=chunk_ids,
            include=["embeddings", "documents", "metadatas"],
        )
        tvdb_col.add(
            ids=[safe_id(x) for x in batch["ids"]],
            documents=batch["documents"] or [""] * len(batch["ids"]),
            metadatas=[
                {k: v for k, v in m.items() if isinstance(v, (str, int, float, bool))}
                for m in (batch["metadatas"] or [{}] * len(batch["ids"]))
            ],
            vectors=[np.array(v, dtype=np.float32).tolist() for v in batch["embeddings"]],
        )
        loaded += len(batch["ids"])

    tvdb_col.flush()
    print(f"  {name}: synced {loaded} new drawers")
    return loaded


def main():
    t0 = time.monotonic()
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] turbovecdb sync starting")

    chroma = chromadb.PersistentClient(path=PALACE)
    tvdb = turbovecdb.connect(TVDB_PATH)

    total_new = sum(sync_collection(chroma, tvdb, name) for name in COLLECTIONS)

    tvdb.close()

    state = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            state = json.load(f)

    state["last_sync_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    state["last_sync_new_drawers"] = total_new
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    elapsed = time.monotonic() - t0
    print(f"Sync complete: {total_new} new drawers in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
```

Save to `/opt/proj/Uncle-J-s-Refinery/scripts/turbovecdb-sync.py`.

- [ ] **Step 2: Run and verify it's idempotent (second run adds 0)**

```bash
cd /opt/proj/Uncle-J-s-Refinery
CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI \
  .venv/bin/python3 scripts/turbovecdb-sync.py
```

Expected: `in sync (296126 drawers)` on both collections, `0 new drawers`.

- [ ] **Step 3: Commit**

```bash
git add scripts/turbovecdb-sync.py
git commit -m "feat: turbovecdb-sync.py — incremental nightly sync after mine cron"
```

---

## Task 4: Benchmark script

**Files:**
- Create: `scripts/turbovecdb-benchmark.py`

Samples 200 vectors directly from ChromaDB (no re-embedding), queries both backends, records p50/p95 latency and recall@10 per collection. Appends one JSON line to `state/turbovecdb-eval.jsonl`.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Weekly benchmark: ChromaDB vs turbovecdb latency + recall@10."""

import json
import os
import random
import time

import chromadb
import numpy as np
import turbovecdb

PALACE = os.path.expanduser("~/.mempalace/palace")
TVDB_PATH = os.path.expanduser("~/.turbovecdb-eval")
LOG_FILE = "/opt/proj/Uncle-J-s-Refinery/state/turbovecdb-eval.jsonl"
N_QUERIES = 200
K = 10
COLLECTIONS = ["mempalace_drawers"]  # closets too small to be meaningful


def percentile(values, p):
    values = sorted(values)
    idx = int(len(values) * p / 100)
    return values[min(idx, len(values) - 1)]


def benchmark_collection(chroma_client, tvdb, name):
    chroma_col = chroma_client.get_collection(name)
    tvdb_col = tvdb.collection(name, create=False)

    total = chroma_col.count()
    offsets = random.sample(range(total), min(N_QUERIES, total))

    # Fetch query vectors from ChromaDB (one at a time to get specific offsets)
    print(f"  Sampling {len(offsets)} query vectors from {name}...", flush=True)
    query_vecs = []
    for offset in offsets:
        r = chroma_col.get(limit=1, offset=offset, include=["embeddings"])
        query_vecs.append(np.array(r["embeddings"][0], dtype=np.float32))

    chroma_latencies, tvdb_latencies, recalls = [], [], []

    for qvec in query_vecs:
        qlist = qvec.tolist()

        t0 = time.perf_counter()
        cr = chroma_col.query(query_embeddings=[qlist], n_results=K, include=[])
        chroma_latencies.append((time.perf_counter() - t0) * 1000)
        chroma_ids = set(cr["ids"][0])

        t0 = time.perf_counter()
        tr = tvdb_col.query(vector=qlist, k=K, include=[])
        tvdb_latencies.append((time.perf_counter() - t0) * 1000)
        tvdb_ids = set(tr.ids)

        recalls.append(len(chroma_ids & tvdb_ids) / K)

    return {
        "collection": name,
        "n_queries": len(query_vecs),
        "chroma_p50_ms": round(percentile(chroma_latencies, 50), 3),
        "chroma_p95_ms": round(percentile(chroma_latencies, 95), 3),
        "tvdb_p50_ms": round(percentile(tvdb_latencies, 50), 3),
        "tvdb_p95_ms": round(percentile(tvdb_latencies, 95), 3),
        "recall_at_10_mean": round(sum(recalls) / len(recalls), 4),
        "recall_at_10_min": round(min(recalls), 4),
        "total_drawers": total,
    }


def main():
    random.seed(int(time.time()))  # different sample each run
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] turbovecdb benchmark starting ({N_QUERIES} queries, k={K})")

    chroma = chromadb.PersistentClient(path=PALACE)
    tvdb = turbovecdb.connect(TVDB_PATH)

    # Time the turbovecdb cold-start index build
    t0 = time.monotonic()
    _ = turbovecdb.connect(TVDB_PATH).collection("mempalace_drawers", create=False).count()
    build_ms = round((time.monotonic() - t0) * 1000, 1)

    results = []
    for name in COLLECTIONS:
        print(f"  Benchmarking {name}...", flush=True)
        r = benchmark_collection(chroma, tvdb, name)
        results.append(r)
        print(
            f"    chroma p50={r['chroma_p50_ms']}ms p95={r['chroma_p95_ms']}ms | "
            f"tvdb p50={r['tvdb_p50_ms']}ms p95={r['tvdb_p95_ms']}ms | "
            f"recall@10={r['recall_at_10_mean']:.3f}"
        )

    tvdb.close()

    record = {
        "timestamp": ts,
        "tvdb_cold_start_ms": build_ms,
        "results": results,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")

    print(f"Logged to {LOG_FILE}")


if __name__ == "__main__":
    main()
```

Save to `/opt/proj/Uncle-J-s-Refinery/scripts/turbovecdb-benchmark.py`.

- [ ] **Step 2: Run it**

```bash
cd /opt/proj/Uncle-J-s-Refinery
CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI \
  .venv/bin/python3 scripts/turbovecdb-benchmark.py
```

Expected: prints p50/p95 for both backends and recall@10, appends JSON to `state/turbovecdb-eval.jsonl`.

- [ ] **Step 3: Verify log line is valid JSON**

```bash
tail -1 state/turbovecdb-eval.jsonl | python3 -m json.tool | head -20
```

Expected: formatted JSON with `timestamp`, `results`, `recall_at_10_mean`.

- [ ] **Step 4: Commit**

```bash
git add scripts/turbovecdb-benchmark.py
git commit -m "feat: turbovecdb-benchmark.py — weekly p50/p95 + recall@10 vs ChromaDB"
```

---

## Task 5: Weekly report script

**Files:**
- Create: `scripts/turbovecdb-report.sh`

Reads `state/turbovecdb-eval.jsonl`, builds a markdown table of all runs, updates the existing GitHub discussion comment (appends new table, replaces old one).

- [ ] **Step 1: Write the script**

```bash
cat > /opt/proj/Uncle-J-s-Refinery/scripts/turbovecdb-report.sh << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
cd /opt/proj/Uncle-J-s-Refinery
VENV=.venv/bin/python3
LOG=state/turbovecdb-eval.jsonl
COMMENT_ID="DC_kwDOR5_Rks4BBi85"

[[ -f "$LOG" ]] || { echo "No eval log yet"; exit 0; }

# Build markdown table from all log entries
TABLE=$($VENV - << 'EOF'
import json, sys

rows = []
with open("state/turbovecdb-eval.jsonl") as f:
    for line in f:
        r = json.loads(line.strip())
        for result in r.get("results", []):
            rows.append({
                "date": r["timestamp"][:10],
                "drawers": result["total_drawers"],
                "c_p50": result["chroma_p50_ms"],
                "c_p95": result["chroma_p95_ms"],
                "t_p50": result["tvdb_p50_ms"],
                "t_p95": result["tvdb_p95_ms"],
                "recall": result["recall_at_10_mean"],
                "n": result["n_queries"],
            })

print("| Date | Drawers | Chroma p50ms | Chroma p95ms | TurboVec p50ms | TurboVec p95ms | Recall@10 | Queries |")
print("|------|---------|-------------|-------------|---------------|---------------|-----------|---------|")
for row in rows:
    print(f"| {row['date']} | {row['drawers']:,} | {row['c_p50']} | {row['c_p95']} | {row['t_p50']} | {row['t_p95']} | {row['recall']:.3f} | {row['n']} |")
EOF
)

BODY="**Scale test update — weekly benchmark (290K+ drawers, MiniLM 384-d, k=10)**

$TABLE

*Methodology: 200 random drawer vectors sampled from ChromaDB, used as query vectors against both backends. Recall\@10 = |top-10 overlap| / 10. Same machine, sequential runs.*"

# Post update via GraphQL
python3 - << PYEOF
import subprocess, json, sys

mutation = {
    "query": """mutation(\$commentId: ID!, \$body: String!) {
  updateDiscussionComment(input: {commentId: \$commentId, body: \$body}) {
    comment { url }
  }
}""",
    "variables": {
        "commentId": "$COMMENT_ID",
        "body": """$BODY"""
    }
}
result = subprocess.run(
    ["gh", "api", "graphql", "--input", "-"],
    input=json.dumps(mutation), capture_output=True, text=True
)
print(result.stdout)
if result.returncode != 0:
    print("STDERR:", result.stderr, file=sys.stderr)
    sys.exit(1)
PYEOF
SCRIPT
chmod +x /opt/proj/Uncle-J-s-Refinery/scripts/turbovecdb-report.sh
```

- [ ] **Step 2: Run it (requires at least one benchmark log entry)**

```bash
cd /opt/proj/Uncle-J-s-Refinery
bash scripts/turbovecdb-report.sh
```

Expected: GitHub discussion comment updated with markdown table. Verify at `https://github.com/MemPalace/mempalace/discussions/1668#discussioncomment-17182521`.

- [ ] **Step 3: Commit**

```bash
git add scripts/turbovecdb-report.sh
git commit -m "feat: turbovecdb-report.sh — weekly markdown table posted to GitHub discussion"
```

---

## Task 6: Wire benchmark into weekly cron + final PR

- [ ] **Step 1: Add benchmark to crontab (Sunday 5am, report at 6am)**

```bash
crontab -l 2>/dev/null | grep -v "turbovecdb-benchmark\|turbovecdb-report\|turbovecdb-sync" | \
  { cat; \
    echo "30 3 * * * cd /opt/proj/Uncle-J-s-Refinery && CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI .venv/bin/python3 scripts/turbovecdb-sync.py >> state/turbovecdb-sync.log 2>&1"; \
    echo "0 5 * * 0 cd /opt/proj/Uncle-J-s-Refinery && CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI .venv/bin/python3 scripts/turbovecdb-benchmark.py >> state/turbovecdb-benchmark.log 2>&1"; \
    echo "0 6 * * 0 cd /opt/proj/Uncle-J-s-Refinery && bash scripts/turbovecdb-report.sh >> state/turbovecdb-report.log 2>&1"; \
  } | crontab -

crontab -l | grep turbovecdb
```

Expected: 3 cron lines printed.

- [ ] **Step 2: Add crons to healthcheck**

In `healthcheck.sh`, find the `check_crons()` function and add to the EXPECTED array:

```bash
"uncle-j-turbovecdb-sync"
"uncle-j-turbovecdb-benchmark"
"uncle-j-turbovecdb-report"
```

Run `bash healthcheck.sh` to confirm no new failures.

- [ ] **Step 3: Update install-reliability.sh to call turbovecdb-install.sh**

In `install-reliability.sh`, after the existing install steps, add:

```bash
# turbovecdb parallel eval (idempotent)
if [[ -d "$PROJ/scripts" ]]; then
  bash "$PROJ/scripts/turbovecdb-install.sh" 2>/dev/null || true
fi
```

- [ ] **Step 4: Commit everything**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add healthcheck.sh install-reliability.sh
git commit -m "feat: wire turbovecdb eval crons into healthcheck + install-reliability"
```

---

## Self-review

**Spec coverage:**
- ✓ Parallel (separate path, Chroma untouched)
- ✓ Initial load from real 296K palace
- ✓ Nightly sync after mine
- ✓ Real query vectors (not synthetic)
- ✓ p50/p95 latency logged
- ✓ Recall@10 measured
- ✓ Weeks-long (crons run weekly + daily sync)
- ✓ Community reportable (auto-posts to existing discussion comment)

**Gaps:**
- `turbovecdb-install.sh` registers crons but Task 6 also updates them — Task 6's crontab block supersedes Task 1's (correct: Task 6 is the final canonical version, Task 1 is initial scaffolding)
- Report script uses shell heredoc with Python — works but fragile if `$BODY` contains backticks. The Python block handles the actual GraphQL post, shell only builds the table string. Acceptable.
- `safe_id()` is defined in both migrate and sync — acceptable (two standalone scripts, DRY within each script, not across scripts)

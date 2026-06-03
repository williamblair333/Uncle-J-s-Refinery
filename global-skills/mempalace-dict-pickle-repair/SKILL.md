---
name: mempalace-dict-pickle-repair
description: Use when MemPalace healthcheck passes but `mempalace_search` fails with `'dict' object has no attribute 'dimensionality'`, or when dict-format pickles keep recurring after each repair run. Covers manual pickle migration, stdlib-only healthcheck probe design, and finding where the repair pipeline generates broken pickles.
---

## When to use

- `mempalace_search` throws `'dict' object has no attribute 'dimensionality'`
- Healthcheck shows `ok` but search fails (probe gap — healthcheck doesn't do a live query)
- Dict-format pickles keep reappearing after repair (segment UUID changes each time → repair pipeline is the source)

## Root cause pattern

The repair pipeline (`mempalace-repair-now.sh`) writes a new HNSW pickle during each run. If the pipeline uses a code path that serializes the HNSW index as a plain `dict` instead of a `PersistentData` object, every repair run regenerates the broken pickle at a new segment UUID. The healthcheck only checks `CHROMA_API_IMPL` path existence — it does not open the pickle or run a live query — so it passes green while search is broken.

## Step 1 — Manual migration (immediate fix)

# Find the broken segment
grep -r "dimensionality" ~/.local/share/mempalace/  # or wherever the palace data dir is

# Identify the pickle file
find <palace-data-dir>/chroma/chroma-collections -name "*.pkl" | \
  xargs python3 -c "
import pickle, sys
for f in sys.argv[1:]:
    with open(f, 'rb') as fh:
        d = pickle.load(fh)
    print(f, type(d).__name__)
" 2>&1 | grep dict

Once the file is identified:

import pickle, shutil
from chromadb.segment.impl.vector.local_persistent_hnsw import PersistentData

pkl_path = "/path/to/broken/segment.pkl"
shutil.copy(pkl_path, pkl_path + ".bak")

with open(pkl_path, "rb") as f:
    d = pickle.load(f)

if isinstance(d, dict):
    fixed = PersistentData(
        dimensionality=d["dimensionality"],
        total_elements_added=d["total_elements_added"],
        max_seq_id=d["max_seq_id"],
        id_to_label=d["id_to_label"],
        label_to_id=d["label_to_id"],
        id_to_seq_id=d["id_to_seq_id"],
    )
    with open(pkl_path, "wb") as f:
        pickle.dump(fixed, f)
    print("migrated")

## Step 2 — Healthcheck probe (upgrade-durable design)

**Key constraint from pre-mortem:** The probe MUST NOT import `PersistentData` or any chromadb internal. Any chromadb upgrade can rename or remove internal classes — a broken import silently kills the probe. Use stdlib `pickle` only.

# Healthcheck probe — stdlib only, no chromadb import
python3 - <<'EOF'
import pickle, sys, os, glob

palace_data = os.environ.get("MEMPALACE_DATA_DIR", os.path.expanduser("~/.local/share/mempalace"))
pickles = glob.glob(f"{palace_data}/**/index_metadata.pickle", recursive=True)
pickles += glob.glob(f"{palace_data}/**/*.pkl", recursive=True)

broken = []
for p in pickles:
    try:
        with open(p, "rb") as f:
            obj = pickle.load(f)
        if isinstance(obj, dict) and "dimensionality" in obj:
            broken.append(p)
    except Exception as e:
        broken.append(f"{p} (unreadable: {e})")

if broken:
    print("CRIT: dict-format pickle(s) detected — run mempalace-dict-pickle-repair.sh")
    for b in broken:
        print(f"  {b}")
    sys.exit(1)
print("OK: all pickles are proper objects")
EOF

Add this probe to `healthcheck.sh` as a named check (e.g., `check_pickle_format`). It catches the issue that `CHROMA_API_IMPL` path-existence checks miss.

## Step 3 — Fix the repair pipeline root cause

The repair pipeline is writing dict-format pickles. Locate the HNSW serialization step in `mempalace-repair-now.sh` (or the Python it calls) and verify it constructs a `PersistentData` object before pickling, not a raw `dict`. Signs of the bug: any code that does `pickle.dump({...}, f)` where the dict has a `dimensionality` key.

The migration step added to the repair script (`dict → PersistentData` at end of repair) is a safe backstop but not a fix for the root cause — it just cleans up after itself.

## Concurrency note

The stdlib probe (Step 2) does not open a chromadb connection and holds no SQLite WAL lock. It is safe to run while the repair cron is active. Do NOT add a live `mempalace_search` call to the healthcheck — that opens a SegmentAPI instance and contends with the 4am repair cron.

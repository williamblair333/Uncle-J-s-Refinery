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
            f"  {migrated + start_offset}/{total} ({rate:.0f}/s, ETA {eta:.0f}s)   ",
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

    chroma2 = chromadb.PersistentClient(path=PALACE)
    state = {
        "last_sync_counts": {
            name: chroma2.get_collection(name).count()
            for name in COLLECTIONS
        },
        "migration_complete": True,
        "migrated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "turbovecdb_commit": "cf5eb6c6d9cbc79649c8f61c3d45e5850a8c45f0",
    }
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

    print(f"\nMigration complete. State written to {STATE_FILE}")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Incremental sync: load new ChromaDB drawers into turbovecdb."""

import hashlib
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
    clean = raw_id.replace(":", "_").replace("/", "_").replace(".", "_")
    if len(clean) <= 128:
        return clean
    suffix = hashlib.sha256(raw_id.encode()).hexdigest()[:8]
    return clean[:119] + "_" + suffix


def sync_collection(chroma_client, tvdb, name):
    chroma_col = chroma_client.get_collection(name)
    tvdb_col = tvdb.collection(name, dim=384, create=True)

    all_chroma = chroma_col.get(include=[])
    chroma_ids = set(all_chroma["ids"])

    tvdb_ids = set(tvdb_col.get(include=[]).ids)

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

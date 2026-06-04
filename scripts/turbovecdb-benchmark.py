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
COLLECTIONS = ["mempalace_drawers"]


def percentile(values, p):
    values = sorted(values)
    idx = int(len(values) * p / 100)
    return values[min(idx, len(values) - 1)]


def benchmark_collection(chroma_client, tvdb, name):
    chroma_col = chroma_client.get_collection(name)
    tvdb_col = tvdb.collection(name, create=False)

    total = chroma_col.count()
    offsets = random.sample(range(total), min(N_QUERIES, total))

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
    random.seed(int(time.time()))
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] turbovecdb benchmark starting ({N_QUERIES} queries, k={K})")

    chroma = chromadb.PersistentClient(path=PALACE)
    tvdb = turbovecdb.connect(TVDB_PATH)

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
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")

    print(f"Logged to {LOG_FILE}")


if __name__ == "__main__":
    main()

# scripts/bench/run_recall_bench.py
"""Recall benchmark: score the checked-in probe set against the palace.

Complements scripts/turbovecdb-benchmark.py — that rig measures turbovecdb's
agreement with ChromaDB's own output (no independent ground truth); this measures
recall against by-construction ground truth and is backend-labelable, so the same
probes score chroma / turbovecdb / sqlite-vec on equal footing.

Search runs IN-PROCESS via mempalace.searcher.search_memories (the `mempalace
search` CLI prints and returns nothing — unscriptable). The embedding model +
collection load once and are reused across all probes.

Output: state/recall-bench/results-<label>.json  (gitignored, like all state/).

Usage:
  .venv/bin/python scripts/bench/run_recall_bench.py --label chroma-baseline --k 5
  .venv/bin/python scripts/bench/run_recall_bench.py --label turbovecdb --backend turbovecdb --k 5
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import recall_lib  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
PALACE = os.path.expanduser("~/.mempalace/palace")
DEFAULT_PROBES = Path(__file__).parent / "probes.jsonl"


def keys_from_hits(hits):
    """Map search_memories hits -> stable drawer keys, preserving rank order.

    Prefers the internal full path + chunk index (_source_file_full,
    _chunk_index); falls back to the public 'source_file' basename.
    """
    keys = []
    for h in hits:
        src = h.get("_source_file_full") or h.get("source_file") or ""
        keys.append(recall_lib.drawer_key(src, h.get("_chunk_index")))
    return keys


def score_probes(probes, search_fn, k):
    """search_fn(query, k) -> (hits, engine): a rank-ordered list of hit dicts
    plus the engine that served them ('vector' | 'bm25').

    Engine is reported BY the search call, not inferred from the hits — a vector
    failure whose BM25 fallback returns zero hits must still read 'bm25', else
    vector_failure_rate would undercount its own worst case."""
    out = []
    for p in probes:
        hits, engine = search_fn(p["query"], k)
        retrieved = keys_from_hits(hits)
        out.append({
            "id": p["id"],
            "origin": p.get("origin", "?"),
            "k": k,
            "expect": p["expect"],
            "retrieved": retrieved,
            "engine": engine,
            "recall": recall_lib.recall_at_k(set(p["expect"]), retrieved, k),
        })
    return out


def build_payload(per_probe, label, k, palace, n_probes_loaded):
    return {
        "label": label,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "palace": palace,
        "k": k,
        "n_probes_loaded": n_probes_loaded,
        "aggregate": recall_lib.aggregate(per_probe),
        "per_probe": per_probe,
    }


def _make_live_searcher(backend):
    """Build a search_fn closed over the loaded collection. Imports mempalace
    lazily so the pure functions above stay test-importable without it.

    Adaptation (2026-06-12): Two known ChromaDB compat errors require BM25 fallback:

    1. "ef or M is too small" — search_memories over-fetches n_results * 3 for
       the hybrid re-rank. With 316k+ drawers and ChromaDB's default HNSW ef=10,
       some queries fail when the candidate pool size exceeds ef.

    2. "np.uint64(<N>)" — _pin_hnsw_threads calls collection.modify() which fails
       with "Schema is missing defaults.float_list.vector_index" in chromadb 1.5.8;
       the ValueError is caught internally and re-raised as a stringified uint64.

    Both are ChromaDB version bugs, not mempalace logic bugs. On either error we
    retry with vector_disabled=True (BM25-only). Affected probes are tagged with
    '_bench_fallback' in their hits so downstream analysis can identify them.
    """
    from mempalace.searcher import search_memories
    if backend:
        os.environ.setdefault("MEMPALACE_BACKEND", backend)  # honored by config resolution

    def search_fn(query, k):
        res = search_memories(query=query, palace_path=PALACE, n_results=k)
        if isinstance(res, dict) and res.get("error"):
            err = res["error"]
            # Any vector-path error: retry with BM25-only fallback. Engine is
            # reported as 'bm25' regardless of how many hits BM25 returns — even
            # an empty fallback is a vector failure that must be counted.
            res = search_memories(
                query=query, palace_path=PALACE, n_results=k, vector_disabled=True
            )
            if isinstance(res, dict) and res.get("error"):
                raise SystemExit(
                    f"search failed (vector err: {err!r}; bm25 fallback: {res['error']!r})"
                )
            hits = (res or {}).get("results", [])
            for h in hits:
                h["_bench_fallback"] = f"bm25:{err}"
            return hits, "bm25"
        return (res or {}).get("results", []), "vector"

    return search_fn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True,
                    help="run label: chroma-baseline | turbovecdb | sqlite-vec")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--backend", default=None, help="passthrough to mempalace backend")
    ap.add_argument("--probes", default=str(DEFAULT_PROBES))
    args = ap.parse_args()

    # Label becomes the output filename (results-<label>.json) — constrain it so
    # a path separator / traversal can't write outside state/recall-bench/.
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.label):
        ap.error("--label must match [A-Za-z0-9._-]+ (it names the output file)")

    probes = recall_lib.load_probes(args.probes)
    search_fn = _make_live_searcher(args.backend)
    per_probe = score_probes(probes, search_fn, args.k)
    payload = build_payload(per_probe, args.label, args.k, PALACE, len(probes))

    out_dir = REPO / "state/recall-bench"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"results-{args.label}.json"
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    agg = payload["aggregate"]
    print(f"recall-bench[{args.label}] k={args.k}: "
          f"mean={agg['recall_at_k_mean']} min={agg['recall_at_k_min']} "
          f"perfect={agg['n_perfect']}/{agg['n_probes']} zero={agg['n_zero']} "
          f"vector_failure_rate={agg['vector_failure_rate']} "
          f"(bm25_served={agg['n_vector_fallback']}/{agg['n_probes']}) -> {out}")
    if agg["vector_failure_rate"]:
        print(f"  WARNING: {agg['n_vector_fallback']}/{agg['n_probes']} probes fell back to "
              f"BM25 (vector path errored). '{args.label}' recall is NOT a clean vector number.")


if __name__ == "__main__":
    main()

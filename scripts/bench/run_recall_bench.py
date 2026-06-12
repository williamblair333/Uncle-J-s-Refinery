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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import recall_lib  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
PALACE = os.path.expanduser("~/.mempalace/palace")
DEFAULT_PROBES = Path(__file__).parent / "probes.jsonl"

# Child program for ISOLATED mode: one search in a fresh process, so a ChromaDB
# hnswlib SIGSEGV on a pathological query (confirmed at 316k drawers) crashes the
# child, not the whole run. The query arrives as argv[1] — never a shell string.
_CHILD_SRC = r'''
import json, os, sys
q, k = sys.argv[1], int(sys.argv[2])
if len(sys.argv) > 3 and sys.argv[3]:          # optional backend passthrough
    os.environ.setdefault("MEMPALACE_BACKEND", sys.argv[3])
from mempalace.searcher import search_memories
p = os.path.expanduser("~/.mempalace/palace")
res = search_memories(query=q, palace_path=p, n_results=k)
eng = "vector"
if isinstance(res, dict) and res.get("error"):
    res = search_memories(query=q, palace_path=p, n_results=k, vector_disabled=True)
    eng = "bm25"
hits = (res or {}).get("results", []) if isinstance(res, dict) else []
print("RESULT" + json.dumps({"hits": hits, "engine": eng}))
'''


def _parse_child(returncode, stdout):
    """Map a child process result -> (hits, engine). A non-zero exit (the
    hnswlib segfault) becomes ([], 'segfault'); a missing RESULT line is treated
    as a failure ([], 'bm25') rather than a silent empty success."""
    if returncode != 0:
        return [], "segfault"
    for line in stdout.splitlines():
        if line.startswith("RESULT"):
            try:
                payload = json.loads(line[len("RESULT"):])
            except json.JSONDecodeError:
                continue  # a stray 'RESULT...' library line, not our sentinel
            return payload.get("hits") or [], payload.get("engine", "vector")
    return [], "bm25"


def _run_child(query, k, child_src=_CHILD_SRC, python=None, backend=None):
    """Run one search in a subprocess. The query is passed as an argv element
    (list form, no shell=True) so arbitrary drawer text can never be executed.
    `backend` (optional) is forwarded so isolate mode still honors --backend."""
    argv = [python or sys.executable, "-c", child_src, query, str(k)]
    if backend:
        argv.append(backend)
    proc = subprocess.run(argv, capture_output=True, text=True)
    return _parse_child(proc.returncode, proc.stdout)


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
            # Sibling-accept (M0.5): expect is an equivalence class of near-dup
            # drawers; retrieving any one within k is a full hit, not 1/N credit.
            "recall": recall_lib.hit_at_k(set(p["expect"]), retrieved, k),
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


def _make_isolated_searcher(segfaults, backend=None):
    """Per-probe subprocess searcher. A child that exits non-zero (hnswlib
    SIGSEGV) is recorded as a vector failure (engine 'bm25', so it counts in
    vector_failure_rate) and its query is appended to `segfaults` for reporting —
    the parent run never dies. `backend` is forwarded to each child."""
    def search_fn(query, k):
        hits, engine = _run_child(query, k, backend=backend)
        if engine == "segfault":
            segfaults.append(query)
            engine = "bm25"  # a crash is a vector failure for the aggregate
        return hits, engine
    return search_fn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True,
                    help="run label: chroma-baseline | turbovecdb | sqlite-vec")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--backend", default=None, help="passthrough to mempalace backend")
    ap.add_argument("--probes", default=str(DEFAULT_PROBES))
    ap.add_argument("--isolate", action=argparse.BooleanOptionalAction, default=True,
                    help="run each probe in its own subprocess so a ChromaDB "
                         "hnswlib segfault is a recorded failure, not a dead run "
                         "(default: on)")
    args = ap.parse_args()

    # Label becomes the output filename (results-<label>.json) — constrain it so
    # a path separator / traversal can't write outside state/recall-bench/.
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.label):
        ap.error("--label must match [A-Za-z0-9._-]+ (it names the output file)")

    probes = recall_lib.load_probes(args.probes)
    segfaults = []
    if args.isolate:
        search_fn = _make_isolated_searcher(segfaults, backend=args.backend)
    else:
        search_fn = _make_live_searcher(args.backend)
    per_probe = score_probes(probes, search_fn, args.k)
    payload = build_payload(per_probe, args.label, args.k, PALACE, len(probes))
    payload["aggregate"]["n_segfault"] = len(segfaults)

    out_dir = REPO / "state/recall-bench"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"results-{args.label}.json"
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    agg = payload["aggregate"]
    print(f"recall-bench[{args.label}] k={args.k}: "
          f"mean={agg['recall_at_k_mean']} min={agg['recall_at_k_min']} "
          f"perfect={agg['n_perfect']}/{agg['n_probes']} zero={agg['n_zero']} "
          f"vector_failure_rate={agg['vector_failure_rate']} "
          f"(bm25_served={agg['n_vector_fallback']}/{agg['n_probes']}) "
          f"segfault={agg['n_segfault']} -> {out}")
    if agg["vector_failure_rate"]:
        print(f"  WARNING: {agg['n_vector_fallback']}/{agg['n_probes']} probes fell back to "
              f"BM25 (vector path errored). '{args.label}' recall is NOT a clean vector number.")
    if segfaults:
        print(f"  WARNING: {len(segfaults)} probe(s) SIGSEGV'd ChromaDB hnswlib "
              f"(recorded as vector failures): {segfaults}")


if __name__ == "__main__":
    main()

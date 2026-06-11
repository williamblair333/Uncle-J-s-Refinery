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

NOTE on _source_file_full / _chunk_index (verified 2026-06-11):
  search_memories() strips both _source_file_full and _chunk_index from results
  in _finalize_candidate_hits (searcher.py:839-843) before returning. Hits only
  expose 'source_file' (basename). keys_from_hits therefore always produces
  'basename::0' for live search results. Probe expect keys in probes.jsonl must
  use the same 'basename::0' form (chunk index is not recoverable from results).
  The by-construction guarantee still holds: the distinctive phrase from a drawer
  must surface that drawer's file in top-K, regardless of which chunk index.
"""
import argparse
import json
import os
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

    NOTE: search_memories() strips _source_file_full and _chunk_index before
    returning (searcher.py _finalize_candidate_hits). In live search, this
    function will always use the 'source_file' fallback path and produce
    'basename::0'. Tests that inject hits with _source_file_full/_chunk_index
    still work correctly via the primary path — the fallback is the live reality.
    """
    keys = []
    for h in hits:
        src = h.get("_source_file_full") or h.get("source_file") or ""
        keys.append(recall_lib.drawer_key(src, h.get("_chunk_index")))
    return keys


def score_probes(probes, search_fn, k):
    """search_fn(query, k) -> list of hit dicts (rank-ordered)."""
    out = []
    for p in probes:
        hits = search_fn(p["query"], k)
        retrieved = keys_from_hits(hits)
        out.append({
            "id": p["id"],
            "origin": p.get("origin", "?"),
            "k": k,
            "expect": p["expect"],
            "retrieved": retrieved,
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

    Backend env var behavior (verified 2026-06-11 against config.py):
    - MEMPALACE_BACKEND is honored: priority is config.json > MEMPALACE_BACKEND > default.
    - os.environ.setdefault() sets it only if not already present, so an existing
      env var overrides the --backend flag. For the chroma baseline (default backend
      when nothing is configured), no env var action is needed.
    - config.json backend takes priority over the env var, so if the live palace has
      backend=chroma in config.json, setting MEMPALACE_BACKEND=turbovecdb via this
      function will have NO effect. To switch backends, edit config.json or use
      mempalace config set-backend <name>. The --backend flag here only works when
      config.json does NOT specify a backend.

    Vector fallback (verified 2026-06-11): the live palace has a diverged HNSW
    segment (np.uint64 count error). search_memories() with vector_disabled=True
    uses BM25-only via sqlite and works reliably. We try vector first; if it
    errors, fall back to vector_disabled=True automatically.
    """
    from mempalace.searcher import search_memories
    if backend:
        os.environ.setdefault("MEMPALACE_BACKEND", backend)

    def search_fn(query, k):
        # Try vector first; auto-fall-back to BM25-only on HNSW failure.
        res = search_memories(query=query, palace_path=PALACE, n_results=k)
        if isinstance(res, dict) and res.get("error"):
            # HNSW diverged or otherwise broken — retry with BM25-only fallback.
            res = search_memories(query=query, palace_path=PALACE, n_results=k,
                                  vector_disabled=True)
        if isinstance(res, dict) and res.get("error"):
            raise SystemExit(f"search failed: {res['error']}")
        return (res or {}).get("results", [])

    return search_fn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True,
                    help="run label: chroma-baseline | turbovecdb | sqlite-vec")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--backend", default=None, help="passthrough to mempalace backend")
    ap.add_argument("--probes", default=str(DEFAULT_PROBES))
    args = ap.parse_args()

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
          f"perfect={agg['n_perfect']}/{agg['n_probes']} zero={agg['n_zero']} -> {out}")


if __name__ == "__main__":
    main()

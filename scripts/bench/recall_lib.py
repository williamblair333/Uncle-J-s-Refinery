# scripts/bench/recall_lib.py
"""Pure functions for the recall benchmark. STDLIB ONLY — no chromadb/mempalace
imports here, so CI can test this module with `pip install pytest` alone.

A drawer is identified for ground-truth purposes by (source_file basename,
chunk_index) -> "basename::chunk". This is stable across backends: the same
drawer keeps the same key whether retrieved via ChromaDB, turbovecdb, or
sqlite-vec, which is what makes one probe set comparable across backends.
"""
from pathlib import Path
import json


class ProbeError(ValueError):
    """A probe record is malformed."""


def drawer_key(source_file, chunk_index) -> str:
    """Stable identity for a drawer: '<basename>::<chunk_index>'.

    chunk_index None/missing -> 0 (single-chunk drawer). Empty source -> '?'.
    """
    name = Path(source_file).name if source_file else "?"
    ci = chunk_index if isinstance(chunk_index, int) else 0
    return f"{name}::{ci}"


def recall_at_k(expected: set, retrieved_keys, k: int) -> float:
    """Fraction of expected drawer keys present in the first k DISTINCT drawers.

    Task 2.7: dedup retrieved keys to distinct drawers (preserving first-seen
    rank order) BEFORE applying the top-k cut. Without this, a few giant mined
    files whose many chunks collapse to one drawer key monopolize the top-k and
    push the real target past the cut, making recall degenerate (~0). The metric
    answers "is the target among the top-k distinct drawers retrieved", which is
    the right question once chunks collapse to drawers.
    """
    if not expected:
        raise ProbeError("expected set is empty")
    distinct = []
    seen = set()
    for key in retrieved_keys:
        if key not in seen:
            seen.add(key)
            distinct.append(key)
    top = set(distinct[:k])
    found = len(expected & top)
    return round(found / len(expected), 4)


def validate_probe(p) -> None:
    if not isinstance(p, dict):
        raise ProbeError(f"probe is not an object: {p!r}")
    if not p.get("id"):
        raise ProbeError(f"probe missing id: {p!r}")
    if not p.get("query"):
        raise ProbeError(f"probe {p.get('id')} missing query")
    expect = p.get("expect")
    if not isinstance(expect, list) or not expect:
        raise ProbeError(f"probe {p.get('id')} expect must be a non-empty list")


def load_probes(path):
    probes = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        p = json.loads(line)
        validate_probe(p)
        probes.append(p)
    ids = [p["id"] for p in probes]
    if len(ids) != len(set(ids)):
        raise ProbeError("duplicate probe ids in file")
    return probes


def aggregate(per_probe):
    recalls = [r["recall"] for r in per_probe]
    n = len(recalls)
    # A probe served by the BM25 fallback (vector path errored) is tagged
    # engine="bm25". A high rate means "chroma-baseline" is partly BM25 — the
    # recall number is only citable alongside this rate. Legacy records with no
    # engine key default to "vector" so they never inflate the rate.
    n_bm25 = sum(1 for r in per_probe if r.get("engine", "vector") == "bm25")
    return {
        "n_probes": n,
        "recall_at_k_mean": round(sum(recalls) / n, 4) if n else 0.0,
        "recall_at_k_min": round(min(recalls), 4) if n else 0.0,
        "n_perfect": sum(1 for r in recalls if r == 1.0),
        "n_zero": sum(1 for r in recalls if r == 0.0),
        "n_vector_fallback": n_bm25,
        "vector_failure_rate": round(n_bm25 / n, 4) if n else 0.0,
    }

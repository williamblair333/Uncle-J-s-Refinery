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
import string


class ProbeError(ValueError):
    """A probe record is malformed."""


def drawer_key(source_file, chunk_index) -> str:
    """Stable identity for a drawer: '<basename>::<chunk_index>'.

    chunk_index None/missing -> 0 (single-chunk drawer). Empty source -> '?'.
    """
    name = Path(source_file).name if source_file else "?"
    ci = chunk_index if isinstance(chunk_index, int) else 0
    return f"{name}::{ci}"


def _distinct_topk(retrieved_keys, k: int) -> set:
    """Top-k DISTINCT drawer keys, first-seen rank order preserved.

    Task 2.7: dedup BEFORE the cut. A few giant mined files whose many chunks
    collapse to one drawer key would otherwise monopolize the top-k and push the
    real target past the cut, making recall degenerate (~0).
    """
    distinct = []
    seen = set()
    for key in retrieved_keys:
        if key not in seen:
            seen.add(key)
            distinct.append(key)
    return set(distinct[:k])


def recall_at_k(expected: set, retrieved_keys, k: int) -> float:
    """Fraction of expected drawer keys present in the first k DISTINCT drawers.

    The metric answers "is the target among the top-k distinct drawers retrieved",
    which is the right question once chunks collapse to drawers. For multi-target
    expect sets this is fractional; for sibling-accept known-item scoring use
    hit_at_k instead.
    """
    if not expected:
        raise ProbeError("expected set is empty")
    found = len(expected & _distinct_topk(retrieved_keys, k))
    return round(found / len(expected), 4)


def hit_at_k(expected: set, retrieved_keys, k: int) -> float:
    """1.0 if ANY expected drawer key is among the top-k distinct drawers, else 0.0.

    M0.5 sibling-accept: `expected` is an equivalence class of near-duplicate
    drawers that all contain the probe's distinctive phrase. Retrieving any one
    of them is a success — they hold the same content, so fractional credit would
    penalize the engine for picking a different-but-equally-correct copy. This is
    standard known-item recall with the relevant item generalized to its
    duplicate-set.
    """
    if not expected:
        raise ProbeError("expected set is empty")
    return 1.0 if expected & _distinct_topk(retrieved_keys, k) else 0.0


# Tokens that are unembeddable garbage in a probe query: hash/uuid/session-id
# fragments and random high-entropy strings. A distinctive PHRASE made of real
# words survives; an id smuggled in as a "word" does not.
_HEXSET = set(string.hexdigits.lower())


def _token_is_garbage(tok: str) -> bool:
    t = tok.strip().lower()
    if not t:
        return False
    # Random long token (no English word reaches 20 chars); kills base64-ish ids.
    if len(t) >= 20:
        return True
    # Hash/uuid fragment: hex (hyphens allowed) with at least one digit, len>=6.
    # The digit requirement spares real all-hex words like "facade"/"decade".
    h = t.replace("-", "")
    if len(h) >= 6 and h and all(c in _HEXSET for c in h) and any(c.isdigit() for c in h):
        return True
    # Id-like token: mostly digits (e.g. "48c8", "0061"). Short tech tokens with a
    # single trailing digit (sqlite3, minilm6) stay under the 0.4 ratio.
    digits = sum(c.isdigit() for c in t)
    if len(t) >= 4 and digits / len(t) > 0.4:
        return True
    return False


def phrase_is_clean(phrase: str) -> bool:
    """True if the phrase is a usable probe query: real multi-word content with
    no hash/uuid/random-token garbage and no adjacent duplicate words.

    Drops the exact failure classes that produced the live recall 0.0:
    session-id/uuid fragments, hex hashes, random base64 tokens, and
    low-information repeats like "command command".
    """
    words = phrase.split()
    if len(words) < 2:
        return False
    lowered = [w.lower() for w in words]
    for a, b in zip(lowered, lowered[1:]):
        if a == b:  # adjacent duplicate -> low information
            return False
    return not any(_token_is_garbage(w) for w in words)


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

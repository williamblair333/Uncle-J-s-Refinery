# Accuracy Instrumentation (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the mission's #1 priority (Right) a measurable number. A versioned, by-construction ground-truth probe set drives a deterministic recall benchmark against the live palace; a correction ledger turns "right-answer rate" into a trend line; a citation stop-hook structurally closes the fabrication path; usage counters fill the Phase 1 audit's `missing` rows. The single LLM step is the final backend-decision memo (judgment), per spec P1.

**Architecture:** A new `scripts/bench/` package (stdlib + already-installed `mempalace`/`chromadb` for the *harness only*, never for tests) holds: (1) `recall_lib.py` — pure functions (recall@k, probe schema validation, aggregation) with zero heavy imports, so CI tests them with `pip install pytest` alone; (2) `seed_probes.py` — samples drawers via `chromadb` read-only and builds probes by construction (distinctive n-gram from a drawer's own text → that drawer's `(source_file, chunk_index)` must appear in top-K); (3) `run_recall_bench.py` — loads the embedding model once and calls `mempalace.searcher.search_memories()` **in-process** per probe (the CLI prints and is unscriptable; `search_memories` returns `_source_file_full` + `_chunk_index`). Probes live in `scripts/bench/probes.jsonl` (checked in). Results write to `state/recall-bench/results-<label>.json` (gitignored, like all `state/`). The correction ledger is a bash appender + a CLAUDE.md/skill snippet. The citation hook is an exit-0-always Stop hook matching the existing async chain. Usage counters extend `collect_benefits.py`.

**Tech Stack:** Python 3.11 stdlib (json, re, math, argparse, datetime, pathlib, hashlib); bash runners; `mempalace`/`chromadb` from `.venv` for the harness scripts only; pytest (existing CI harness, 0 API calls, no heavy deps).

**Principles (from spec):** deterministic-first (P1) — only Task 8 (memo) uses judgment; everything else is scripts. Local-canonical (P2) — probes and corrections are versioned local files, model-agnostic. Missing data is explicit (`missing` list), never guessed — inherited from Phase 1. The recall benchmark **complements** `turbovecdb-benchmark.py`: that rig measures turbovecdb's agreement *with ChromaDB's own output* (no independent ground truth); this harness measures recall against by-construction ground truth, and is backend-labelable so the same probes score chroma / turbovecdb / sqlite-vec on equal footing.

**Verified against reality (2026-06-11):**
- `mempalace search` CLI exists (`--wing --room --results --backend`) but **prints** results and returns `None` — not scriptable for structured ground truth. The harness uses `mempalace.searcher.search_memories(query, palace_path, n_results=k)` which returns `{"results": [{"_source_file_full":..., "_chunk_index":..., "source_file": basename, ...}]}`.
- Palace path: `~/.mempalace/palace` (from `~/.mempalace/config.json`, `collection_name: mempalace_drawers`). Confirmed via `collect_benefits.py` comment: `~/.mempalace/palace/chroma.sqlite3` is live; `~/.mempalace/chroma.sqlite3` is a stale stub.
- Model load + first query takes >2 min cold; so the harness loads once and reuses the collection across all probes.
- Stop hooks in `.claude/settings.json` are `{"type":"command","command":"bash .../foo.sh  # uncle-j-<name>","async":true}` — fire-and-forget, no `continue:false`. New hook follows this exactly and must `exit 0` unconditionally.
- Transcripts: `~/.claude/projects/-opt-proj-Uncle-J-s-Refinery/*.jsonl`; `tool_use` blocks live in `message.content[]` with `name` + `input`; the Stop hook receives the transcript path on stdin as `transcript_path`.
- Cron convention (`features/mempalace/install.sh`): `0 4 * * * nice -n 19 flock -n /tmp/<name>.lock <cmd> >> state/<name>.log 2>&1`, registered via marker-commented crontab lines.
- CI `test-audit` job: `actions/setup-python@v5` (3.11) + `pip install pytest` + `python -m pytest tests/<f> -v`.

---

### Task 1: Recall library — pure functions (CI-testable, no heavy imports)

**Files:**
- Create: `scripts/bench/__init__.py` (empty)
- Create: `scripts/bench/recall_lib.py`
- Test: `tests/test_recall_bench.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_recall_bench.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "bench"))
import recall_lib

REPO = Path(__file__).parent.parent


def test_drawer_key_normalizes_path_and_chunk():
    assert recall_lib.drawer_key("/home/x/a.txt", 3) == "a.txt::3"
    assert recall_lib.drawer_key("/home/x/a.txt", None) == "a.txt::0"
    assert recall_lib.drawer_key("", 0) == "?::0"


def test_recall_at_k_hit_and_miss():
    # expected one of {a::0}, retrieved keys in order
    assert recall_lib.recall_at_k({"a::0"}, ["b::0", "a::0", "c::0"], k=3) == 1.0
    assert recall_lib.recall_at_k({"a::0"}, ["b::0", "c::0"], k=3) == 0.0
    # multi-target: 1 of 2 found within k -> 0.5
    assert recall_lib.recall_at_k({"a::0", "d::0"}, ["a::0", "x::0"], k=3) == 0.5


def test_recall_at_k_respects_k_cutoff():
    # target only at position 4; k=3 must not count it
    assert recall_lib.recall_at_k({"t::0"}, ["a::0", "b::0", "c::0", "t::0"], k=3) == 0.0


def test_validate_probe_accepts_well_formed():
    p = {"id": "p1", "query": "foo bar", "expect": ["a.txt::0"], "origin": "seed"}
    recall_lib.validate_probe(p)  # no raise


def test_validate_probe_rejects_missing_fields():
    import pytest
    for bad in [{"query": "x", "expect": ["a::0"]},          # no id
                {"id": "p", "expect": ["a::0"]},             # no query
                {"id": "p", "query": "x", "expect": []},     # empty expect
                {"id": "p", "query": "x", "expect": "a::0"}]: # expect not list
        with pytest.raises(recall_lib.ProbeError):
            recall_lib.validate_probe(bad)


def test_aggregate_computes_mean_and_perk():
    per_probe = [
        {"id": "p1", "recall": 1.0, "k": 5},
        {"id": "p2", "recall": 0.0, "k": 5},
        {"id": "p3", "recall": 0.5, "k": 5},
    ]
    agg = recall_lib.aggregate(per_probe)
    assert agg["n_probes"] == 3
    assert agg["recall_at_k_mean"] == 0.5
    assert agg["recall_at_k_min"] == 0.0
    assert agg["n_perfect"] == 1
    assert agg["n_zero"] == 1


def test_load_probes_roundtrip(tmp_path):
    f = tmp_path / "p.jsonl"
    f.write_text('{"id":"p1","query":"q","expect":["a::0"],"origin":"seed"}\n'
                 '\n'  # blank line tolerated
                 '{"id":"p2","query":"q2","expect":["b::0"],"origin":"hand"}\n')
    probes = recall_lib.load_probes(f)
    assert [p["id"] for p in probes] == ["p1", "p2"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /opt/proj/Uncle-J-s-Refinery && .venv/bin/python -m pytest tests/test_recall_bench.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recall_lib'`

- [ ] **Step 3: Write the library**

```python
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
    """Fraction of expected drawer keys present in the first k retrieved keys."""
    if not expected:
        raise ProbeError("expected set is empty")
    top = set(retrieved_keys[:k])
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
    return {
        "n_probes": n,
        "recall_at_k_mean": round(sum(recalls) / n, 4) if n else 0.0,
        "recall_at_k_min": round(min(recalls), 4) if n else 0.0,
        "n_perfect": sum(1 for r in recalls if r == 1.0),
        "n_zero": sum(1 for r in recalls if r == 0.0),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_recall_bench.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/bench/__init__.py scripts/bench/recall_lib.py tests/test_recall_bench.py
git commit -m "feat(bench): recall_lib — pure recall@k + probe-schema functions"
```

---

### Task 2: Probe seeder — by-construction ground truth

**Files:**
- Create: `scripts/bench/seed_probes.py`
- Test: `tests/test_recall_bench.py` (append)

The seeder samples drawers from the live palace and, for each, extracts a distinctive phrase from that drawer's own text to use as the query — so the ground-truth drawer is correct by construction. The pure phrase-extraction logic is unit-tested; the chromadb sampling is isolated behind `main()`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_recall_bench.py
import seed_probes


def test_distinctive_phrase_picks_rare_multiword_run():
    # 'quantum flux capacitor' is rare; stopwords/common words avoided.
    text = ("the the the and of to a in\n"
            "quantum flux capacitor calibration sequence\n"
            "the and of to in a the and")
    phrase = seed_probes.distinctive_phrase(text, n_words=4)
    assert phrase is not None
    assert "quantum" in phrase
    # phrase is a contiguous run drawn from the text
    assert phrase in " ".join(text.split())


def test_distinctive_phrase_none_for_too_short():
    assert seed_probes.distinctive_phrase("hi there", n_words=4) is None


def test_distinctive_phrase_is_deterministic():
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"
    a = seed_probes.distinctive_phrase(text, n_words=4)
    b = seed_probes.distinctive_phrase(text, n_words=4)
    assert a == b


def test_build_probe_record_shape():
    rec = seed_probes.build_probe_record(
        idx=2, query="quantum flux capacitor calibration",
        source_file="/x/notes.md", chunk_index=1)
    assert rec["id"] == "seed-0002"
    assert rec["query"] == "quantum flux capacitor calibration"
    assert rec["expect"] == ["notes.md::1"]
    assert rec["origin"] == "seed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recall_bench.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'seed_probes'`

- [ ] **Step 3: Write the seeder**

```python
# scripts/bench/seed_probes.py
"""Seed a by-construction ground-truth probe set from the live palace.

For each sampled drawer we extract a distinctive multi-word phrase FROM THAT
DRAWER'S OWN TEXT and use it as the query. The drawer the phrase came from is,
by construction, the correct top-K answer (expect = ["<basename>::<chunk>"]).

Sampling uses chromadb read-only (already in .venv) — NOT used by tests.
Pure phrase extraction (`distinctive_phrase`, `build_probe_record`) is unit-tested
and stdlib-only.

Usage:
  .venv/bin/python scripts/bench/seed_probes.py --n 25 --out scripts/bench/probes.jsonl
Hand-written probes (known project facts) are appended manually after seeding;
they use "origin":"hand" and are preserved across re-seeds (see --append).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import recall_lib  # noqa: E402  (pure helpers reused for drawer_key)

PALACE = os.path.expanduser("~/.mempalace/palace")
COLLECTION = "mempalace_drawers"

# Words too common to make a query distinctive. Deliberately small + explicit.
_STOP = {
    "the", "and", "of", "to", "a", "in", "is", "it", "for", "on", "with", "as",
    "at", "by", "an", "be", "or", "this", "that", "from", "are", "was", "but",
    "not", "you", "we", "i", "if", "so", "do", "no",
}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")


def distinctive_phrase(text, n_words=4):
    """Return a deterministic contiguous run of n_words 'content' words.

    Picks the first window (scanning left to right) in which every word is a
    content word (>=3 chars, not a stopword). Deterministic: no randomness,
    same text always yields the same phrase. None if no such window exists.
    """
    words = _WORD_RE.findall(text)
    content_flags = [w.lower() not in _STOP for w in words]
    for i in range(0, len(words) - n_words + 1):
        if all(content_flags[i:i + n_words]):
            return " ".join(words[i:i + n_words])
    return None


def build_probe_record(idx, query, source_file, chunk_index):
    return {
        "id": f"seed-{idx:04d}",
        "query": query,
        "expect": [recall_lib.drawer_key(source_file, chunk_index)],
        "origin": "seed",
    }


def _sample_drawers(n):
    """Read-only chromadb sample of (document, metadata) pairs. Deterministic
    offsets (evenly spaced) so re-seeds are reproducible for a given palace."""
    import chromadb
    client = chromadb.PersistentClient(path=PALACE)
    col = client.get_collection(COLLECTION)
    total = col.count()
    if total == 0:
        raise SystemExit("palace empty — nothing to seed")
    step = max(1, total // (n * 3))  # over-sample; many drawers yield no phrase
    offsets = list(range(0, total, step))
    out = []
    for off in offsets:
        r = col.get(limit=1, offset=off, include=["documents", "metadatas"])
        docs = r.get("documents") or []
        metas = r.get("metadatas") or []
        if docs and metas:
            out.append((docs[0] or "", metas[0] or {}))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=25, help="target number of seed probes")
    ap.add_argument("--n-words", type=int, default=4)
    ap.add_argument("--out", default=str(Path(__file__).parent / "probes.jsonl"))
    ap.add_argument("--append", action="store_true",
                    help="keep existing origin!=seed probes from --out")
    args = ap.parse_args()

    kept = []
    out_path = Path(args.out)
    if args.append and out_path.exists():
        kept = [p for p in recall_lib.load_probes(out_path) if p.get("origin") != "seed"]

    records, seen_keys = [], set()
    for doc, meta in _sample_drawers(args.n):
        phrase = distinctive_phrase(doc, args.n_words)
        if not phrase:
            continue
        key = recall_lib.drawer_key(meta.get("source_file", ""), meta.get("chunk_index"))
        if key in seen_keys:  # one probe per drawer
            continue
        seen_keys.add(key)
        records.append(build_probe_record(len(records) + 1, phrase,
                                          meta.get("source_file", ""),
                                          meta.get("chunk_index")))
        if len(records) >= args.n:
            break

    all_probes = records + kept
    out_path.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in all_probes))
    print(f"seed_probes: wrote {len(records)} seed + {len(kept)} kept probes -> {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, then seed against the live palace**

Run: `.venv/bin/python -m pytest tests/test_recall_bench.py -v && .venv/bin/python scripts/bench/seed_probes.py --n 25 --out scripts/bench/probes.jsonl && wc -l scripts/bench/probes.jsonl`
Expected: 11 passed; `probes.jsonl` has ~25 lines. (First palace open is slow, ~30-90 s — `chromadb` loads the HNSW segment.)

- [ ] **Step 5: Add ~5 hand-written probes from known project facts**

These exercise real retrieval (not n-gram echo). Each query is a natural question; `expect` is the drawer key it must surface — find each key by running `.venv/bin/python scripts/bench/run_recall_bench.py` after Task 3 with a temporary one-line probe and reading the top hit's `_source_file_full::_chunk_index`, OR by grepping the palace SQLite for the source file. Example shape to append to `scripts/bench/probes.jsonl` (replace keys with verified ones):

```json
{"id":"hand-0001","query":"where does the memory palace live on disk","expect":["bqnif6sk6.txt::0"],"origin":"hand"}
```

Document in the commit body how each hand probe's `expect` key was verified.

- [ ] **Step 6: Commit**

```bash
git add scripts/bench/seed_probes.py scripts/bench/probes.jsonl tests/test_recall_bench.py
git commit -m "feat(bench): probe seeder (by-construction ground truth) + checked-in probes.jsonl"
```

---

### Task 3: Recall benchmark harness — in-process search, labeled output

**Files:**
- Create: `scripts/bench/run_recall_bench.py`
- Test: `tests/test_recall_bench.py` (append)

The harness imports `mempalace.searcher.search_memories` and runs every probe against the loaded collection, scoring with `recall_lib`. Backend selectable via `--backend` (passed through to mempalace) and labeled via `--label` for cross-backend comparison.

- [ ] **Step 1: Write the failing tests** (test the pure scoring/record-building seam; the live-search seam is injected so tests need no model)

```python
# append to tests/test_recall_bench.py
import run_recall_bench


def test_keys_from_hits_uses_full_path_and_chunk():
    hits = [
        {"_source_file_full": "/x/a.txt", "_chunk_index": 2},
        {"_source_file_full": "/y/b.md", "_chunk_index": None},
        {"source_file": "c.txt"},  # fallback: only basename present
    ]
    keys = run_recall_bench.keys_from_hits(hits)
    assert keys == ["a.txt::2", "b.md::0", "c.txt::0"]


def test_score_probes_with_fake_searcher():
    probes = [
        {"id": "p1", "query": "find a", "expect": ["a.txt::0"], "origin": "seed"},
        {"id": "p2", "query": "find z", "expect": ["z.txt::0"], "origin": "seed"},
    ]

    def fake_search(query, k):
        if "a" in query:
            return [{"_source_file_full": "/d/a.txt", "_chunk_index": 0}]
        return [{"_source_file_full": "/d/x.txt", "_chunk_index": 0}]

    per_probe = run_recall_bench.score_probes(probes, fake_search, k=5)
    assert per_probe[0]["recall"] == 1.0
    assert per_probe[1]["recall"] == 0.0
    assert per_probe[0]["retrieved"] == ["a.txt::0"]


def test_build_result_payload_shape():
    per_probe = [{"id": "p1", "recall": 1.0, "k": 5, "expect": ["a::0"], "retrieved": ["a::0"]}]
    payload = run_recall_bench.build_payload(per_probe, label="chroma-baseline",
                                             k=5, palace="/p", n_probes_loaded=1)
    assert payload["label"] == "chroma-baseline"
    assert payload["k"] == 5
    assert payload["aggregate"]["recall_at_k_mean"] == 1.0
    assert payload["per_probe"][0]["id"] == "p1"
    assert "timestamp" in payload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recall_bench.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'run_recall_bench'`

- [ ] **Step 3: Write the harness**

```python
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
    lazily so the pure functions above stay test-importable without it."""
    from mempalace.searcher import search_memories
    kwargs = {}
    if backend:
        os.environ.setdefault("MEMPALACE_BACKEND", backend)  # honored by config resolution

    def search_fn(query, k):
        res = search_memories(query=query, palace_path=PALACE, n_results=k)
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
```

- [ ] **Step 4: Run tests, then run the real baseline**

Run: `.venv/bin/python -m pytest tests/test_recall_bench.py -v && .venv/bin/python scripts/bench/run_recall_bench.py --label chroma-baseline --k 5 && python3 -c "import json;d=json.load(open('state/recall-bench/results-chroma-baseline.json'));print('mean',d['aggregate']['recall_at_k_mean'],'zero',d['aggregate']['n_zero'])"`
Expected: 14 passed; a `results-chroma-baseline.json` with `recall_at_k_mean` near 1.0 for seed probes (by construction they should mostly land top-5). Investigate any `n_zero > 0` seed probe: a zero means the hybrid re-rank buried the exact-phrase drawer — that is a real, citable finding for the backend memo, not a harness bug.

> **Note for executor:** verify `MEMPALACE_BACKEND` is the env var mempalace honors — check `MempalaceConfig` resolution in `.venv/lib/python3.11/site-packages/mempalace/` (the CLI uses `--backend`; the in-process `search_memories` has no backend arg, so backend selection for turbovecdb/sqlite-vec runs goes through config/env). If the env var name differs, fix `_make_live_searcher` only. For the chroma baseline (default backend) this is moot.

- [ ] **Step 5: Commit**

```bash
git add scripts/bench/run_recall_bench.py tests/test_recall_bench.py
git commit -m "feat(bench): recall harness — in-process labeled recall@k over probe set"
```

---

### Task 4: gitignore state/recall-bench + bench runner script

**Files:**
- Modify: `.gitignore` (add `state/recall-bench/` is unnecessary if `state/` already ignored — verify; results live under already-ignored `state/`)
- Create: `scripts/bench/run-recall-bench.sh`

- [ ] **Step 1: Confirm state/ is gitignored** — Phase 1 outputs (`state/payoff-audit/`) are already gitignored via `state/` rules. Verify the recall results inherit this.

Run: `git check-ignore state/recall-bench/results-x.json; echo "exit=$?"`
Expected: prints the path, `exit=0` (ignored). If not ignored, add `state/recall-bench/` under the existing `state/` block in `.gitignore` (keep `probes.jsonl` tracked — it lives in `scripts/bench/`, not `state/`).

- [ ] **Step 2: Write the runner**

```bash
# scripts/bench/run-recall-bench.sh
#!/usr/bin/env bash
# Recall benchmark runner — deterministic, no LLM. Default label chroma-baseline.
# Usage: scripts/bench/run-recall-bench.sh [label] [k]
set -euo pipefail
cd "$(dirname "$0")/../.."
LABEL="${1:-chroma-baseline}"
K="${2:-5}"
.venv/bin/python scripts/bench/run_recall_bench.py --label "$LABEL" --k "$K"
echo "Done. Results: state/recall-bench/results-${LABEL}.json"
```

- [ ] **Step 3: Make executable + smoke test**

Run: `chmod +x scripts/bench/run-recall-bench.sh && bash scripts/bench/run-recall-bench.sh chroma-baseline 5`
Expected: same summary line as Task 3 Step 4.

- [ ] **Step 4: Commit**

```bash
git add scripts/bench/run-recall-bench.sh .gitignore
git commit -m "feat(bench): run-recall-bench.sh runner; confirm results gitignored"
```

---

### Task 5: Correction ledger — appender + counter + Claude snippet

**Files:**
- Create: `scripts/log-correction.sh`
- Modify: `scripts/audit/collect_benefits.py` (add corrections counter)
- Modify: `tests/test_audit.py` (append a test for the new counter)
- Modify: `CLAUDE.md` (add the invocation instruction snippet)

The ledger is deterministic capture: a bash script appends a validated JSONL event to `state/corrections.jsonl` (gitignored). A CLAUDE.md snippet instructs Claude to invoke it whenever the user corrects a factual error. The counter surfaces in `collect_benefits.py` so right-answer/correction trend feeds the Phase 1 scorecard.

- [ ] **Step 1: Write the failing test for the counter** (pure-function seam, hermetic — no real ledger file)

```python
# append to tests/test_audit.py
def test_count_corrections_parses_jsonl_and_buckets_by_component():
    import collect_benefits
    sample = (
        '{"ts":"2026-06-11T10:00:00Z","component":"mempalace","summary":"wrong path"}\n'
        '{"ts":"2026-06-11T11:00:00Z","component":"mempalace","summary":"stale fact"}\n'
        '{"ts":"2026-06-11T12:00:00Z","component":"telegram","summary":"bad offset claim"}\n'
        'not json — tolerated\n'
    )
    counts = collect_benefits.count_corrections(sample)
    assert counts["mempalace"] == 2
    assert counts["telegram"] == 1
    assert counts["_unparsed"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_audit.py -k corrections -v`
Expected: FAIL with `AttributeError: module 'collect_benefits' has no attribute 'count_corrections'`

- [ ] **Step 3a: Add the counter to collect_benefits.py**

Add this function (stdlib only, beside the other counters):

```python
def count_corrections(text):
    """Count correction-ledger events per component. Tolerates non-JSON lines
    (counted under _unparsed) so a truncated ledger never crashes the audit."""
    import json
    counts = {}
    for line in filter(str.strip, text.splitlines()):
        try:
            ev = json.loads(line)
            comp = ev.get("component") or "_uncategorized"
        except (ValueError, AttributeError):
            comp = "_unparsed"
        counts[comp] = counts.get(comp, 0) + 1
    return counts
```

And wire it into `main()` (after the `mempalace_counts` block, before `result["missing"] = missing`):

```python
    corr_path = REPO / "state/corrections.jsonl"
    if corr_path.exists():
        result["components"].setdefault("guardrails-discipline", {})
        result["components"]["guardrails-discipline"]["corrections"] = \
            count_corrections(corr_path.read_text(errors="replace"))
    else:
        missing.append(str(corr_path))
```

> **Note for executor:** `guardrails-discipline` may already hold `hook_blocks`; `setdefault({})` then assigning a key preserves it. Verify the existing assignment uses `=` with a fresh dict — if so change it to `setdefault` + key-assign so both keys coexist. Confirm with the test below.

- [ ] **Step 3b: Write the appender script**

```bash
# scripts/log-correction.sh
#!/usr/bin/env bash
# Append a validated factual-correction event to state/corrections.jsonl.
# Deterministic capture — NO LLM. Invoked by Claude when the user corrects a
# factual error (see CLAUDE.md), or by hand.
# Usage: scripts/log-correction.sh <component> <summary...>
set -euo pipefail
cd "$(dirname "$0")/.."

COMPONENT="${1:-}"
shift || true
SUMMARY="$*"

if [[ -z "$COMPONENT" || -z "$SUMMARY" ]]; then
  echo "usage: log-correction.sh <component> <summary>" >&2
  exit 2
fi

mkdir -p state
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Build the JSON with python3 for safe escaping — never hand-concat user text.
python3 - "$TS" "$COMPONENT" "$SUMMARY" <<'PY' >> state/corrections.jsonl
import json, sys
ts, component, summary = sys.argv[1], sys.argv[2], sys.argv[3]
print(json.dumps({"ts": ts, "component": component, "summary": summary}, ensure_ascii=False))
PY
echo "logged correction: $COMPONENT — $SUMMARY"
```

- [ ] **Step 3c: Add the CLAUDE.md instruction snippet** — under an existing operating-rules-style section, add:

```markdown
### Correction ledger

When the user corrects a *factual* error you made (wrong path, stale claim, bad
number, fabricated detail), immediately run:

    bash scripts/log-correction.sh <component> "<one-line summary of the correction>"

Use a component id from `scripts/audit/components.json` (e.g. mempalace, telegram,
routing-policy). This is deterministic capture only — log first, then continue.
The correction count feeds the pay-for-itself scorecard's right-answer trend.
```

- [ ] **Step 4: Run tests + smoke-test the appender**

Run: `.venv/bin/python -m pytest tests/test_audit.py -k corrections -v && chmod +x scripts/log-correction.sh && bash scripts/log-correction.sh mempalace "verified ledger smoke test" && tail -1 state/corrections.jsonl && .venv/bin/python scripts/audit/collect_benefits.py && python3 -c "import json;d=json.load(open('state/payoff-audit/benefits.json'));print(d['components'].get('guardrails-discipline'))"`
Expected: test passes; ledger line is valid JSON with `ts/component/summary`; benefits.json shows `corrections` under `guardrails-discipline` alongside `hook_blocks`.

- [ ] **Step 5: Confirm corrections.jsonl is gitignored** (under `state/`); commit code only.

Run: `git check-ignore state/corrections.jsonl; echo exit=$?`
Expected: ignored, `exit=0`.

- [ ] **Step 6: Commit**

```bash
git add scripts/log-correction.sh scripts/audit/collect_benefits.py tests/test_audit.py CLAUDE.md
git commit -m "feat(bench): correction ledger appender + scorecard counter + CLAUDE.md snippet"
```

---

### Task 6: Usage counters for dreaming / ralph / telegram (audit gap)

**Files:**
- Modify: `scripts/audit/collect_benefits.py` (add `log_age_and_runs` + wiring)
- Modify: `tests/test_audit.py` (append)

Fills the Phase 1 scorecard rows that were `missing`. Reads the real logs verified in `state/`: `dreaming-last-run.txt` (ISO timestamp) + `dreaming.log` (run/skip lines), telegram `telegram-gateway.log` (`[ts] Polling...` lines). **Ralph has no log in `state/` (verified — `find` found none)**, so ralph goes to `missing`, never guessed.

- [ ] **Step 1: Write the failing tests** (pure parsers, hermetic)

```python
# append to tests/test_audit.py
def test_last_run_age_days_from_iso():
    import collect_benefits, datetime
    now = datetime.datetime(2026, 6, 11, tzinfo=datetime.timezone.utc)
    age = collect_benefits.iso_age_days("2026-06-09T13:03:17Z", now=now)
    assert age == 2.0
    assert collect_benefits.iso_age_days("garbage", now=now) is None


def test_count_log_lines_matching():
    import collect_benefits
    log = ("[2026-06-11 08:20:01] Polling Telegram (offset=1)\n"
           "[2026-06-11 08:20:01] getUpdates returned ok=false\n"
           "[2026-06-11 08:21:01] Polling Telegram (offset=2)\n")
    assert collect_benefits.count_matching(log, "Polling Telegram") == 2


def test_count_dreaming_runs_vs_skips():
    import collect_benefits
    log = ("2026-06-10T13:03:17Z skip: no traces since ...\n"
           "2026-06-09T02:00:00Z dreamed: wrote 3 playbooks\n"
           "2026-06-08T02:00:00Z skip: no traces\n")
    stats = collect_benefits.dreaming_run_stats(log)
    assert stats["skips"] == 2
    assert stats["runs"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_audit.py -k "age or matching or dreaming" -v`
Expected: FAIL with AttributeError on the new functions.

- [ ] **Step 3: Add the parsers + wiring to collect_benefits.py**

```python
def iso_age_days(ts_str, now=None):
    """Age in days (rounded to 0.1) of an ISO-8601 'Z' timestamp; None if unparseable."""
    import datetime
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        t = datetime.datetime.strptime(ts_str.strip(), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc)
    except (ValueError, AttributeError):
        return None
    return round((now - t).total_seconds() / 86400.0, 1)


def count_matching(text, needle):
    return sum(1 for line in text.splitlines() if needle in line)


def dreaming_run_stats(text):
    runs = count_matching(text, "dreamed:")
    skips = count_matching(text, "skip:")
    return {"runs": runs, "skips": skips}
```

Wire into `main()` before `result["missing"] = missing`:

```python
    # dreaming: last-run age + run/skip counts
    last_run = REPO / "state/dreaming-last-run.txt"
    dream_log = REPO / "state/dreaming.log"
    dream = {}
    if last_run.exists():
        age = iso_age_days(last_run.read_text())
        if age is not None:
            dream["last_run_age_days"] = age
    if dream_log.exists():
        dream.update(dreaming_run_stats(dream_log.read_text(errors="replace")))
    if dream:
        result["components"]["dreaming"] = dream
    else:
        missing.append("dreaming logs (state/dreaming-last-run.txt, state/dreaming.log)")

    # telegram: poll count as a liveness proxy
    tg_log = REPO / "state/telegram-gateway.log"
    if tg_log.exists():
        result["components"]["telegram"] = {
            "poll_count": count_matching(tg_log.read_text(errors="replace"), "Polling Telegram")}
    else:
        missing.append(str(tg_log))

    # ralph: no log shipped (verified 2026-06-11). Explicit gap — never guessed.
    missing.append("ralph: no run log present in state/ (verify if/when ralph logging lands)")
```

- [ ] **Step 4: Run tests + the real collector**

Run: `.venv/bin/python -m pytest tests/test_audit.py -v && .venv/bin/python scripts/audit/collect_benefits.py && python3 -c "import json;d=json.load(open('state/payoff-audit/benefits.json'));print('dreaming',d['components'].get('dreaming'));print('telegram',d['components'].get('telegram'));print('missing',d['missing'])"`
Expected: all audit tests pass; `dreaming` shows `last_run_age_days` (~1-2 d given last run 2026-06-10) + run/skip counts; `telegram` shows a nonzero `poll_count`; `missing` lists the ralph gap explicitly.

- [ ] **Step 5: Commit**

```bash
git add scripts/audit/collect_benefits.py tests/test_audit.py
git commit -m "feat(audit): usage counters for dreaming/telegram; ralph gap made explicit"
```

---

### Task 7: Citation audit Stop-hook script

**Files:**
- Create: `scripts/citation-audit.sh`
- Create: `scripts/citation_audit.py` (the parser; bash hook is a thin wrapper, Python does the JSONL work)
- Modify: `.claude/settings.json` (append one Stop hook, async, exit-0-always)
- Test: `tests/test_recall_bench.py` is wrong home; create `tests/test_citation_audit.py`
- Modify: `.github/workflows/ci.yml` (extend test-audit or add a job — see Task 9)

Scans the session transcript for URLs, cross-checks each against `WebFetch`/`Bash gh` tool uses *in the same transcript*, appends verified/unverified records to `state/citation-audit.jsonl`. Slots into the existing async Stop chain; must `exit 0` always.

- [ ] **Step 1: Write the failing tests** (pure transcript parsing, hermetic, fixture-driven)

```python
# tests/test_citation_audit.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import citation_audit as ca


def _line(obj):
    import json
    return json.dumps(obj)


def test_extract_urls_from_assistant_text():
    rec = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "see https://github.com/foo/bar and http://x.io/y page"}]}}
    urls = ca.extract_urls_from_record(rec)
    assert "https://github.com/foo/bar" in urls
    assert "http://x.io/y" in urls


def test_collect_fetched_urls_from_webfetch_and_gh():
    recs = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "WebFetch", "input": {"url": "https://github.com/foo/bar"}}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash",
             "input": {"command": "gh api repos/foo/bar/issues/3"}}]}},
    ]
    fetched = ca.collect_fetched_evidence(recs)
    assert "https://github.com/foo/bar" in fetched["urls"]
    assert any("repos/foo/bar/issues/3" in c for c in fetched["gh_cmds"])


def test_classify_url_verified_by_webfetch():
    fetched = {"urls": {"https://github.com/foo/bar"}, "gh_cmds": []}
    assert ca.classify_url("https://github.com/foo/bar", fetched) == "verified"


def test_classify_url_verified_by_gh_path_match():
    fetched = {"urls": set(), "gh_cmds": ["gh api repos/foo/bar/issues/3"]}
    assert ca.classify_url("https://github.com/foo/bar/issues/3", fetched) == "verified"


def test_classify_url_unverified():
    fetched = {"urls": set(), "gh_cmds": []}
    assert ca.classify_url("https://example.com/made-up", fetched) == "unverified"


def test_audit_transcript_builds_records(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join([
        _line({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "WebFetch", "input": {"url": "https://real.io/a"}}]}}),
        _line({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "cite https://real.io/a and https://fake.io/b"}]}}),
    ]))
    records = ca.audit_transcript(f)
    by_url = {r["url"]: r["status"] for r in records}
    assert by_url["https://real.io/a"] == "verified"
    assert by_url["https://fake.io/b"] == "unverified"
    assert all("session" in r and "ts" in r for r in records)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_citation_audit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'citation_audit'`

- [ ] **Step 3: Write the Python parser**

```python
# scripts/citation_audit.py
"""Citation audit: scan a Claude Code session transcript for URLs the assistant
emitted, cross-check each against WebFetch / `gh` evidence in the SAME transcript,
and append verified/unverified records to state/citation-audit.jsonl.

Deterministic — NO LLM. Structurally closes the fabrication path: a URL the
assistant stated but never fetched/verified is flagged 'unverified'.

Invoked by scripts/citation-audit.sh (Stop hook). Reads transcript path from the
hook stdin JSON ('transcript_path'). STDLIB ONLY.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / "state/citation-audit.jsonl"
# URLs as the assistant would write them; trailing punctuation trimmed.
_URL_RE = re.compile(r"https?://[^\s\)\]\}>\"'`]+")
_TRAILING = ".,;:!?"


def _clean(url):
    return url.rstrip(_TRAILING)


def extract_urls_from_record(rec):
    urls = set()
    if rec.get("type") != "assistant":
        return urls
    for block in (rec.get("message", {}).get("content") or []):
        if isinstance(block, dict) and block.get("type") == "text":
            for m in _URL_RE.findall(block.get("text", "")):
                urls.add(_clean(m))
    return urls


def collect_fetched_evidence(records):
    """URLs fetched via WebFetch + raw `gh` command strings run via Bash."""
    urls, gh_cmds = set(), []
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        for block in (rec.get("message", {}).get("content") or []):
            if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                continue
            name = block.get("name")
            inp = block.get("input") or {}
            if name == "WebFetch" and inp.get("url"):
                urls.add(_clean(inp["url"]))
            elif name == "Bash":
                cmd = inp.get("command", "")
                if re.search(r"\bgh\b", cmd):
                    gh_cmds.append(cmd)
    return {"urls": urls, "gh_cmds": gh_cmds}


def classify_url(url, fetched):
    if url in fetched["urls"]:
        return "verified"
    # gh path-match: a github URL's path appearing in a gh command counts.
    path = re.sub(r"^https?://(www\.)?github\.com/", "", url)
    if path and path != url:
        for cmd in fetched["gh_cmds"]:
            if path in cmd:
                return "verified"
    return "unverified"


def _read_records(transcript_path):
    records = []
    for line in Path(transcript_path).read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def audit_transcript(transcript_path):
    records = _read_records(transcript_path)
    fetched = collect_fetched_evidence(records)
    stated = set()
    for rec in records:
        stated |= extract_urls_from_record(rec)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    session = Path(transcript_path).stem
    out = []
    for url in sorted(stated):
        out.append({"ts": ts, "session": session, "url": url,
                    "status": classify_url(url, fetched)})
    return out


def main():
    # Hook stdin: {"transcript_path": "...", ...}. Tolerate missing/empty.
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return
    tp = payload.get("transcript_path")
    if not tp or not Path(tp).exists():
        return
    records = audit_transcript(tp)
    if not records:
        return
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write the bash hook wrapper** (exit-0-always, matches the chain style)

```bash
# scripts/citation-audit.sh — Claude Code Stop hook.
# Greps the session transcript for URLs, cross-checks against WebFetch/gh evidence
# in the same transcript, appends verified/unverified records to
# state/citation-audit.jsonl. Deterministic; exit 0 always (like the other Stop hooks).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Prefer repo .venv python; fall back to python3. Never fail the hook.
PY="$SCRIPT_DIR/../.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3 || true)"
[[ -n "$PY" ]] || exit 0
"$PY" "$SCRIPT_DIR/citation_audit.py" </dev/stdin >/dev/null 2>&1 || true
exit 0
```

- [ ] **Step 5: Register the Stop hook in `.claude/settings.json`** — append a new object to the existing `Stop` array, matching the established shape:

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "bash /opt/proj/Uncle-J-s-Refinery/scripts/citation-audit.sh  # uncle-j-citation-audit",
      "async": true
    }
  ]
}
```

(Insert as a new sibling of the existing `session-notify` / `skill-suggest` / `skill-link` / `mempalace-mine-convos` Stop entries. Do not modify the others.)

- [ ] **Step 6: Run tests + smoke-test against a real transcript**

Run: `.venv/bin/python -m pytest tests/test_citation_audit.py -v && echo "{\"transcript_path\": \"$(ls -t ~/.claude/projects/-opt-proj-Uncle-J-s-Refinery/*.jsonl | head -1)\"}" | bash scripts/citation-audit.sh; echo "hook exit=$?"; tail -3 state/citation-audit.jsonl 2>/dev/null`
Expected: 6 passed; hook exits 0; `state/citation-audit.jsonl` gains records with `status: verified|unverified` (the live transcript has github URLs — some verified via the WebFetch/gh evidence, some unverified).

- [ ] **Step 7: Confirm ledger gitignored + commit**

Run: `git check-ignore state/citation-audit.jsonl; echo exit=$?`
Expected: ignored.

```bash
git add scripts/citation_audit.py scripts/citation-audit.sh .claude/settings.json tests/test_citation_audit.py
git commit -m "feat(bench): citation-audit Stop hook — flag unverified URLs to state ledger"
```

---

### Task 8: Weekly cron + CI wiring

**Files:**
- Modify: `features/mempalace/install.sh` (add a weekly recall-bench cron alongside the existing crons) — OR a dedicated `scripts/bench/install-bench-cron.sh` if the executor prefers not to touch the mempalace installer. **Decision: add a standalone `scripts/bench/install-bench-cron.sh`** following the same `nice -n 19 / flock -n / marker-comment` convention, so the recall benchmark's cron lifecycle is independent of the mempalace feature installer.
- Modify: `.github/workflows/ci.yml` (add `test-bench` job covering the pure functions)
- Modify: `CHANGELOG.md`, `HANDOFF.md`, `docs/RELIABILITY.md` (the PreToolUse commit guard blocks commits unless these three are staged)

- [ ] **Step 1: Write the cron installer** (mirrors `features/mempalace/install.sh` conventions: marker-commented crontab line, `nice -n 19`, `flock -n`, log to `state/`)

```bash
# scripts/bench/install-bench-cron.sh
# Register/remove the weekly recall benchmark cron. Idempotent.
# Convention copied from features/mempalace/install.sh: marker comment + nice + flock.
# Usage: install-bench-cron.sh [install|remove]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
MARKER="# uncle-j-recall-bench-cron"
ACTION="${1:-install}"

# Sunday 05:00 — after the nightly mine (3am) + repair (4am) so the palace is fresh.
ENTRY="0 5 * * 0 nice -n 19 flock -n /tmp/recall-bench.lock bash ${REPO}/scripts/bench/run-recall-bench.sh chroma-baseline 5 >> ${REPO}/state/recall-bench.log 2>&1 ${MARKER}"

current="$(crontab -l 2>/dev/null || true)"
cleaned="$(printf '%s\n' "$current" | grep -vF "$MARKER" || true)"

if [[ "$ACTION" == "remove" ]]; then
  printf '%s\n' "$cleaned" | crontab -
  echo "recall-bench cron removed"
else
  { printf '%s\n' "$cleaned"; printf '%s\n' "$ENTRY"; } | crontab -
  echo "recall-bench cron installed: Sunday 05:00, flock-guarded"
fi
```

> **Note for executor:** verify `features/mempalace/install.sh` registers crons via `crontab -l | ... | crontab -` vs a helper like `install_cron`. The earlier grep showed marker constants (`MARKER_CRON`) and `install_cron "$MARKER_CRON" "$CRON_ENTRY"` — if a reusable `install_cron`/`remove_cron` helper exists in `lib/feature-helpers.sh`, source and use it instead of the inline `crontab -` above to match the repo exactly. Keep the marker-comment + `nice -n 19` + `flock -n` invariants either way.

- [ ] **Step 2: Add the CI job** — append after `test-audit` in `.github/workflows/ci.yml`, copying the `test-audit` job structure verbatim (setup-python@v5 / 3.11 / `pip install pytest` / `python -m pytest`):

```yaml
  # ── 7. Recall-bench + citation-audit pure-function tests ─────────────────
  test-bench:
    name: Bench + citation pure-function tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install pytest
        run: pip install pytest

      - name: pytest tests/test_recall_bench.py tests/test_citation_audit.py
        run: python -m pytest tests/test_recall_bench.py tests/test_citation_audit.py -v
```

(The `test-audit` job already runs `tests/test_audit.py`, which now also covers the corrections + usage-counter functions added in Tasks 5–6.)

- [ ] **Step 3: Verify CI tests pass the way CI runs them (system python, pytest only — proves no heavy-dep leak)**

Run: `python3 -m pytest tests/test_recall_bench.py tests/test_citation_audit.py tests/test_audit.py -v`
Expected: all pass with no `chromadb`/`mempalace` import (if any test imports them, it leaked a heavy dep into a unit test — fix by moving the heavy import behind `main()`/a factory, as `run_recall_bench._make_live_searcher` and `seed_probes._sample_drawers` already do).

- [ ] **Step 4: Smoke-test cron install/remove (no live run)**

Run: `bash scripts/bench/install-bench-cron.sh install && crontab -l | grep recall-bench && bash scripts/bench/install-bench-cron.sh remove && (crontab -l | grep -c recall-bench || true)`
Expected: install adds exactly one marked line; remove leaves zero.

- [ ] **Step 5: Update CHANGELOG / HANDOFF / RELIABILITY** (required by the commit guard)

CHANGELOG entry (prepend):

```markdown
## 2026-06-11 — feat: accuracy instrumentation (Improvement Program Phase 2)

### Added
- **`scripts/bench/`**: by-construction ground-truth probe set
  (`probes.jsonl`), `recall_lib.py` pure recall@k functions, `seed_probes.py`
  seeder, `run_recall_bench.py` in-process labeled harness, weekly cron.
  Complements turbovecdb-benchmark.py with independent ground truth; output
  `state/recall-bench/results-<label>.json`.
- **`scripts/log-correction.sh`** + correction counter in the audit scorecard.
- **`scripts/citation-audit.sh`** Stop hook — flags assistant URLs unverified
  against WebFetch/gh evidence to `state/citation-audit.jsonl`.
- Usage counters (dreaming/telegram) added to `collect_benefits.py`; ralph gap
  surfaced explicitly.
- CI `test-bench` job (pure functions, `pip install pytest` only, 0 API calls).
```

Add a short HANDOFF note (current Phase 2 state, how to run a backend-labeled bench) and a `docs/RELIABILITY.md` note (recall-bench weekly cron, flock lock `/tmp/recall-bench.lock`, log `state/recall-bench.log`; citation-audit Stop hook is exit-0-always).

- [ ] **Step 6: Commit**

```bash
git add scripts/bench/install-bench-cron.sh .github/workflows/ci.yml CHANGELOG.md HANDOFF.md docs/RELIABILITY.md
git commit -m "feat(bench): weekly recall-bench cron + test-bench CI job + docs"
```

---

### Task 9: Backend decision memo (in-session judgment — the single permitted LLM step)

This is **not a script**. It is the in-session judgment pass the spec reserves for genuine analysis. Deletion of the ChromaDB repair apparatus (the spec's D2) fires **only after Bill signs the swap** — never automatically.

- [ ] **Step 1: Run the same probe set against each available backend, labeled.**

```bash
bash scripts/bench/run-recall-bench.sh chroma-baseline 5
# turbovecdb (rig already live — PR #23): ensure the turbovecdb eval store is synced,
# then run with the backend selector verified in Task 3 Step 4.
.venv/bin/python scripts/bench/run_recall_bench.py --label turbovecdb --backend turbovecdb --k 5
```

If a `sqlite-vec` backend is wired into mempalace by this point, add `--label sqlite-vec --backend sqlite-vec`. If not, note it as "not yet implementable" — do not fabricate numbers.

- [ ] **Step 2: Pull latency from the existing rig.** Read the most recent record in `state/turbovecdb-eval.jsonl` (`chroma_p50_ms`, `tvdb_p50_ms`, `recall_at_10_mean`) — that rig's recall is *agreement-with-chroma*, distinct from this harness's *ground-truth* recall; report both and label the difference, do not conflate them.

- [ ] **Step 3: Tabulate** recall@k (ground-truth, this harness) + recall@10 (agreement, turbovecdb rig) + p50/p95 latency + maintenance burden (from the Phase 1 scorecard — mempalace's `maintenance_share`, the ~12 repair skills) per candidate: turbovecdb / sqlite-vec / roll-our-own / keep-ChromaDB.

- [ ] **Step 4: Recommend** per the spec's gate: recall ≥ ChromaDB baseline AND zero-maintenance operation. Write the memo to `docs/superpowers/specs/` or `state/` as a session artifact (this is a deliverable doc, not source — confirm with Bill where it lands; do not commit a recommendation as decided).

- [ ] **Step 5: Present to Bill for sign-off.** The MemPalace *application layer* (wings/drawers/mining/diary) is evaluated separately from storage — storage can swap underneath it. Only on explicit sign-off does the swap proceed; the ChromaDB repair-apparatus deletion (repair crons, force-flush private-API hack, ~12 repair skills) is then queued into ROADMAP Phase 4 as the largest Cheap-in-total win. **No deletion in this task.**

---

## Self-review (placeholder / type-consistency check)

- **No placeholders/TBD:** every code block is complete and runnable; the only intentionally manual step is Task 2 Step 5 (hand probe keys must be verified against the live palace) and Task 9 (judgment) — both flagged as such, not left as code stubs.
- **Type consistency:** `drawer_key` always returns `str`; `recall_at_k` returns `float`; `aggregate` consumes `per_probe` dicts with a `recall` float (produced by `score_probes`). `score_probes` builds exactly the keys `aggregate`/`build_payload` read (`id`, `recall`, `k`, `expect`, `retrieved`, `origin`). `validate_probe` checks `id`/`query`/`expect`-nonempty-list — matching the records `build_probe_record` emits and the tests assert.
- **Hermetic tests:** `recall_lib`, `seed_probes.distinctive_phrase/build_probe_record`, `run_recall_bench.keys_from_hits/score_probes/build_payload`, `citation_audit.*`, and the new `collect_benefits` parsers are all stdlib-only and import no `chromadb`/`mempalace` at module top level (heavy imports are inside `main()`/factories). Verified by Task 8 Step 3 running under `pip install pytest` only.
- **Reality-grounded:** harness uses `search_memories` (returns dict) not the printing `search` CLI; palace path `~/.mempalace/palace`; transcript `message.content[]` tool_use shape; Stop-hook async exit-0 shape; cron `nice -n 19`/`flock -n`/marker convention; CI `setup-python@v5` + `pip install pytest`. Each verified live above.
- **Complements, not duplicates:** Task 9 explicitly distinguishes this harness's ground-truth recall from `turbovecdb-benchmark.py`'s agreement-with-chroma recall, and reuses that rig's latency numbers rather than re-measuring.
- **Deterministic-first honored:** Tasks 1–8 are pure scripts; only Task 9 is judgment, and it gates deletion on human sign-off (spec risk note + D2).

---

### Critical Files for Implementation
- /opt/proj/Uncle-J-s-Refinery/scripts/bench/recall_lib.py (new — pure recall@k + probe schema, the CI-tested core)
- /opt/proj/Uncle-J-s-Refinery/scripts/bench/run_recall_bench.py (new — in-process `search_memories` harness, backend-labeled output)
- /opt/proj/Uncle-J-s-Refinery/.venv/lib/python3.11/site-packages/mempalace/searcher.py (reference — `search_memories` return shape: `_source_file_full`, `_chunk_index`; do not edit)
- /opt/proj/Uncle-J-s-Refinery/scripts/audit/collect_benefits.py (modify — correction + dreaming/telegram counters)
- /opt/proj/Uncle-J-s-Refinery/.claude/settings.json (modify — append the exit-0-always citation-audit Stop hook to the existing async chain)
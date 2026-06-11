# scripts/bench/seed_probes.py
"""Seed a by-construction ground-truth probe set from the live palace.

For each sampled drawer we extract a distinctive multi-word phrase FROM THAT
DRAWER'S OWN TEXT and use it as the query. The drawer the phrase came from is,
by construction, the correct top-K answer (expect = ["<basename>::<chunk>"]).

Sampling uses chromadb read-only (already in .venv) — NOT used by tests.
Pure phrase extraction (`distinctive_phrase`, `build_probe_record`) is unit-tested
and stdlib-only.

NOTE: Run under `flock -w 60 /tmp/mempalace-mine-convos.lock` — the cron/stop-hook miners coordinate on this lock.

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

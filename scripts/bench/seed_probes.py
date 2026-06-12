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


def is_seedable_key(key):
    """Reject keys whose source file is unknown ('?::...'). Such a probe is
    unsatisfiable by construction — live search results always carry a real
    source file, so a '?::' expect can never be matched."""
    return not key.startswith("?::")


def build_probe_record(idx, query, expect, origin="seed"):
    """expect is the sibling-set: every drawer key that contains the query phrase
    (M0.5 sibling-accept). origin tags 'seed' (auto-sampled) vs 'hand' (curated)."""
    return {
        "id": f"{origin}-{idx:04d}",
        "query": query,
        "expect": list(expect),
        "origin": origin,
    }


def _tokens(text):
    """Lowercased content-token list, matching distinctive_phrase's tokenizer."""
    return [w.lower() for w in _WORD_RE.findall(text)]


def _contains_token_run(doc_tokens, phrase_tokens):
    """True if phrase_tokens appears as a contiguous run in doc_tokens.

    Token-level (not raw substring) so punctuation/newlines between words don't
    defeat the match — distinctive_phrase joins tokens with single spaces, but
    the source doc has the original separators."""
    n = len(phrase_tokens)
    if n == 0:
        return False
    first = phrase_tokens[0]
    for i in range(len(doc_tokens) - n + 1):
        if doc_tokens[i] == first and doc_tokens[i:i + n] == phrase_tokens:
            return True
    return False


def _trim_boundary_words(text):
    """Drop the first and last whitespace token — chunk edges are cut mid-word
    ('...ome', 'ype...'), and a fragment makes a bad query. Unchanged if too
    short to trim safely."""
    parts = text.split()
    return " ".join(parts[1:-1]) if len(parts) > 2 else text


# Curated distinct-fact probes (origin='hand'): specific verbatim phrases from
# this project's own work, reported separately from auto-sampled seed probes.
# Their ground-truth sibling sets are computed by the SAME scan — an empty set
# (phrase not found verbatim) is dropped with a warning, never guessed.
HAND_PHRASES = [
    "Bootstrap scan registered 26 projects identified 14 conflicts",
    "deleted entire SQLite index byte-identical rebuild",
    "every probe fails to retrieve its own source file",
    "memweave ships no MCP server wrapper is the adoption cost",
    "Docker port conflict prevention SQLite registry",
    "broken-by-construction probes review",
]


def _open_collection():
    import chromadb
    client = chromadb.PersistentClient(path=PALACE)
    col = client.get_collection(COLLECTION)
    if col.count() == 0:
        raise SystemExit("palace empty — nothing to seed")
    return col


def _sample_candidates(col, n, n_words, max_candidates):
    """Evenly-spaced read-only sample -> deduped (phrase, primary_key) candidates.

    Deterministic offsets so a re-seed on the same palace is reproducible. Phrase
    is extracted from the boundary-trimmed doc and must pass phrase_is_clean."""
    total = col.count()
    step = max(1, total // (n * 8))
    out, seen_phrases = [], set()
    for off in range(0, total, step):
        r = col.get(limit=1, offset=off, include=["documents", "metadatas"])
        docs = r.get("documents") or []
        metas = r.get("metadatas") or []
        if not (docs and metas):
            continue
        doc, meta = docs[0] or "", metas[0] or {}
        phrase = distinctive_phrase(_trim_boundary_words(doc), n_words)
        if not phrase or not recall_lib.phrase_is_clean(phrase):
            continue
        if phrase.lower() in seen_phrases:
            continue
        primary = recall_lib.drawer_key(meta.get("source_file", ""), 0)
        if not is_seedable_key(primary):  # unknown source -> unsatisfiable
            continue
        seen_phrases.add(phrase.lower())
        out.append((phrase, primary))
        if len(out) >= max_candidates:
            break
    return out, seen_phrases


def _scan_siblings(col, phrases, batch=5000):
    """ONE read-only pass over every drawer: for each phrase, the set of drawer
    keys whose document contains it as a token run. This is the engine-neutral,
    lexical ground truth (independent of any retrieval backend) that makes the
    recall number comparable across ChromaDB / memweave / sqlite-vec."""
    # Tokenize phrases the SAME way as docs (_tokens), so a hand phrase written
    # with short/stop words or punctuation still aligns to the doc token stream.
    ptoks = [(p, _tokens(p)) for p in phrases]
    sib = {p: set() for p in phrases}
    total = col.count()
    off = 0
    while off < total:
        r = col.get(limit=batch, offset=off, include=["documents", "metadatas"])
        docs = r.get("documents") or []
        metas = r.get("metadatas") or []
        for doc, meta in zip(docs, metas):
            dtoks = _tokens(doc or "")
            if not dtoks:
                continue
            key = recall_lib.drawer_key((meta or {}).get("source_file", ""), 0)
            dset = set(dtoks)
            for p, pt in ptoks:
                if pt[0] in dset and _contains_token_run(dtoks, pt):
                    sib[p].add(key)
        off += batch
        print(f"  scan {min(off, total)}/{total}", file=sys.stderr)
    return sib


def main():
    ap = argparse.ArgumentParser(
        description="Rebuild the recall probe set with content-defined sibling-set "
        "ground truth. Re-seeding is DELIBERATE: it re-samples the live (growing) "
        "palace, so commit the resulting probes.jsonl as the frozen A/B artifact.")
    ap.add_argument("--n", type=int, default=25, help="target number of seed probes")
    ap.add_argument("--n-words", type=int, default=4)
    ap.add_argument("--max-candidates", type=int, default=120,
                    help="cap on candidate phrases scanned (bounds scan cost)")
    ap.add_argument("--max-siblings", type=int, default=4,
                    help="drop phrases appearing in more than this many drawers "
                         "(too generic or over-duplicated -> trivially satisfied)")
    ap.add_argument("--hand", type=int, default=10, help="max curated hand probes")
    ap.add_argument("--out", default=str(Path(__file__).parent / "probes.jsonl"))
    args = ap.parse_args()

    col = _open_collection()
    seed_cands, seen_phrases = _sample_candidates(
        col, args.n, args.n_words, args.max_candidates)
    hand_cands = [(p, None) for p in HAND_PHRASES if p.lower() not in seen_phrases]

    all_phrases = [p for p, _ in seed_cands] + [p for p, _ in hand_cands]
    print(f"seed_probes: scanning {col.count()} drawers for {len(all_phrases)} "
          f"candidate phrases ({len(seed_cands)} seed + {len(hand_cands)} hand)...",
          file=sys.stderr)
    sib = _scan_siblings(col, all_phrases)

    # Greedy DISJOINT acceptance: a candidate is kept only if its sibling set is
    # satisfiable, near-unique (<= max_siblings), and shares no drawer with an
    # already-accepted probe. Disjointness keeps every probe on a distinct
    # cluster (preserves the one-per-drawer invariant) and prevents one mega-file
    # from dominating the headline.
    covered = set()
    seed_recs, hand_recs = [], []
    hand_not_found = hand_filtered = 0

    def _accept(phrase, primary, require_primary):
        nonlocal covered
        S = sib[phrase]
        if require_primary and primary not in S:
            return None  # phrase not actually in its own (post-trim) drawer
        if not S or len(S) > args.max_siblings or (S & covered):
            return None
        covered |= S
        return sorted(S)

    for phrase, primary in seed_cands:
        if len(seed_recs) >= args.n:
            break
        exp = _accept(phrase, primary, require_primary=True)
        if exp is not None:
            seed_recs.append((phrase, exp))

    for phrase, _ in hand_cands:
        if len(hand_recs) >= args.hand:
            break
        exp = _accept(phrase, None, require_primary=False)
        if exp is not None:
            hand_recs.append((phrase, exp))
        elif not sib[phrase]:
            hand_not_found += 1      # phrase absent from the corpus verbatim
        else:
            hand_filtered += 1       # too generic (>max_siblings) or cluster taken

    records = [build_probe_record(i, q, exp, "seed")
               for i, (q, exp) in enumerate(seed_recs, 1)]
    records += [build_probe_record(i, q, exp, "hand")
                for i, (q, exp) in enumerate(hand_recs, 1)]

    out_path = Path(args.out)
    out_path.write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in records))
    print(f"seed_probes: wrote {len(seed_recs)} seed + {len(hand_recs)} hand "
          f"(hand dropped: {hand_not_found} not-found-verbatim, "
          f"{hand_filtered} too-generic/cluster-taken) "
          f"over {len(covered)} distinct drawers -> {out_path}")


if __name__ == "__main__":
    main()

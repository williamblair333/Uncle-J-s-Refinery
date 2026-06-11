# scripts/audit/collect_benefits.py
"""Collector C: benefit signals per component. Every source that can't be read
is listed in `missing` — explicit gaps, no guesses.

Sources:
  1. state/hook-blocks.log                  -> guard catches (guardrails-discipline)
  2. ~/.code-index/_savings.json            -> jcodemunch tokens_saved (total_tokens_saved key)
  3. MemPalace SQLite (~/.mempalace/chroma.sqlite3) -> embedding row count (read-only)
"""
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import audit_lib

HOME = Path.home()
REPO = Path(__file__).resolve().parents[2]
GUARD_RE = re.compile(r"([a-z0-9][a-z0-9_]*(?:-[a-z0-9_]+)*-guard(?:-[a-z0-9_]+)*)", re.I)


def count_blocks(text):
    counts = {}
    for line in filter(str.strip, text.splitlines()):
        m = GUARD_RE.search(line)
        key = m.group(1).lower() if m else "_unparsed"
        counts[key] = counts.get(key, 0) + 1
    return counts


def jcodemunch_saved_tokens():
    """Best-effort scan of ~/.code-index for a persisted tokens_saved figure."""
    best = None
    root = HOME / ".code-index"
    if not root.exists():
        return None
    for p in root.glob("**/*.json"):
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        for m in re.finditer(r'"(?:total_)?tokens_saved"\s*:\s*(\d+)', text):
            best = max(best or 0, int(m.group(1)))
    return best


def mempalace_counts(db_path):
    if not db_path.exists():
        return None
    uri = f"file:{db_path}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            n = conn.execute("SELECT count(*) FROM embeddings").fetchone()[0]
    except sqlite3.Error:
        return None
    return {"embeddings_rows": n}


def main():
    missing, result = [], {"components": {}}

    blocks_path = REPO / "state/hook-blocks.log"
    if blocks_path.exists():
        result["components"]["guardrails-discipline"] = {
            "hook_blocks": count_blocks(blocks_path.read_text(errors="replace"))}
    else:
        missing.append(str(blocks_path))

    saved = jcodemunch_saved_tokens()
    if saved is not None:
        result["components"]["jmunch-retrieval"] = {"tokens_saved_best": saved}
    else:
        missing.append("~/.code-index tokens_saved")

    # Real path: ~/.mempalace/chroma.sqlite3 (not chroma/chroma.sqlite3)
    db = HOME / ".mempalace/chroma.sqlite3"
    mp = mempalace_counts(db)
    if mp:
        result["components"]["mempalace"] = mp
    else:
        missing.append(str(db))

    result["missing"] = missing
    out = audit_lib.write_json(REPO / "state/payoff-audit/benefits.json", result)
    print(f"benefits: {out} (missing: {len(missing)})")


if __name__ == "__main__":
    main()

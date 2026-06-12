#!/usr/bin/env python
"""Fast, read-only memory search over the memweave store.

The stable retrieval entry point for interactive use and later Phase-3 harness /
hook integration ("what did we decide before?"). Unlike index_workspace.py — which
re-scans and indexes first — this opens the existing index and searches directly
(no index(), no writes), so it's fast enough to call per-query from a hook.

Usage:
  .venv-memweave/bin/python scripts/memweave/mw_search.py "why replace mempalace" --k 5
  .venv-memweave/bin/python scripts/memweave/mw_search.py "fts5 fix" --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from onnx_provider import OnnxMiniLMProvider  # noqa: E402

from memweave import MemWeave, MemoryConfig  # noqa: E402
from memweave.config import EmbeddingConfig  # noqa: E402

DEFAULT_WORKSPACE = os.path.expanduser("~/.uncle-j-memory")


async def search_store(workspace, query, *, k=5, min_score=None):
    """Open the existing memweave index read-only and return SearchResult list.
    Does NOT index() — pure query path."""
    provider = OnnxMiniLMProvider()
    config = MemoryConfig(
        workspace_dir=workspace,
        embedding=EmbeddingConfig(model=provider.model),
        progress=False,
    )
    kwargs = {"max_results": k}
    if min_score is not None:
        kwargs["min_score"] = min_score
    async with MemWeave(config, embedding_provider=provider) as mem:
        return await mem.search(query, **kwargs)


def _print_human(results, query):
    if not results:
        print(f"(no memory hits for {query!r})")
        return
    for r in results:
        vs = f"{r.vector_score:.3f}" if r.vector_score is not None else "—"
        ts = f"{r.text_score:.3f}" if r.text_score is not None else "—"
        print(f"[{r.score:.3f} vec={vs} bm25={ts}] {r.path}:{r.start_line}-{r.end_line}")
        print(f"  {r.snippet.strip()[:240]}")


def _print_json(results):
    print(json.dumps(
        [{"path": r.path, "score": round(r.score, 4),
          "start_line": r.start_line, "end_line": r.end_line,
          "snippet": r.snippet} for r in results],
        separators=(",", ":"), ensure_ascii=False))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query")
    ap.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--min-score", type=float, default=None)
    ap.add_argument("--json", action="store_true", help="emit JSON instead of human text")
    args = ap.parse_args()

    if not args.query.strip():
        print("mw_search: empty query", file=sys.stderr)
        return 2

    workspace = os.path.expanduser(args.workspace)
    index_db = Path(workspace) / ".memweave" / "index.sqlite"
    if not index_db.exists():
        print(f"mw_search: no memweave index at {index_db} — run sync_memory.sh first",
              file=sys.stderr)
        return 1

    results = asyncio.run(search_store(workspace, args.query, k=args.k, min_score=args.min_score))
    if args.json:
        _print_json(results)
    else:
        _print_human(results, args.query)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

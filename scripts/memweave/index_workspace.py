#!/usr/bin/env python
"""Index a memweave workspace with the offline ONNX provider; optionally query it.

The proof harness for Phase 2 (does memweave retrieve real Refinery memory?) and
the seed of the Phase-3 search integration. Runs fully offline via OnnxMiniLMProvider.

Usage:
  .venv-memweave/bin/python scripts/memweave/index_workspace.py --workspace ~/.memweave/uncle-j
  .venv-memweave/bin/python scripts/memweave/index_workspace.py --query "how did we fix FTS5 corruption" --k 5
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from onnx_provider import OnnxMiniLMProvider  # noqa: E402

from memweave import MemWeave, MemoryConfig  # noqa: E402
from memweave.config import EmbeddingConfig  # noqa: E402

# Must not sit under a ".memweave"-named dir — see export_transcripts.py note.
DEFAULT_WORKSPACE = os.path.expanduser("~/.uncle-j-memory")


async def run(workspace: str, query: str | None, k: int, force: bool) -> int:
    provider = OnnxMiniLMProvider()
    config = MemoryConfig(
        workspace_dir=workspace,
        embedding=EmbeddingConfig(model=provider.model),
        progress=False,
    )
    async with MemWeave(config, embedding_provider=provider) as mem:
        idx = await mem.index(force=force)
        print(f"index: {idx.files_indexed} indexed, {idx.files_skipped} skipped, "
              f"{idx.chunks_created} chunks  [{idx.duration_ms:.0f}ms]")
        if query:
            results = await mem.search(query, max_results=k)
            print(f"\nquery: {query!r} -> {len(results)} hits")
            for r in results:
                vs = f"{r.vector_score:.3f}" if r.vector_score is not None else "—"
                ts = f"{r.text_score:.3f}" if r.text_score is not None else "—"
                snippet = r.snippet[:140].replace("\n", " ")
                print(f"  [{r.score:.3f} vec={vs} bm25={ts}] {r.path}:{r.start_line}-{r.end_line}")
                print(f"        {snippet}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    ap.add_argument("--query", default=None)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--force", action="store_true", help="re-embed all files regardless of hash")
    args = ap.parse_args()
    return asyncio.run(run(os.path.expanduser(args.workspace), args.query, args.k, args.force))


if __name__ == "__main__":
    raise SystemExit(main())

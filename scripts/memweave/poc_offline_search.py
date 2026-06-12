#!/usr/bin/env python
"""Phase-1 proof: memweave index + hybrid search, fully offline, via the local
ONNX MiniLM provider — no litellm / network / Ollama.

Run under the dedicated 3.12 memweave venv:

    .venv-memweave/bin/python scripts/memweave/poc_offline_search.py

It builds a throwaway workspace of distinct memory .md files, indexes them with
the injected OnnxMiniLMProvider, runs a few semantic queries, and asserts the
right document comes back top-1 AND that the vector path actually ran offline
(vector_score is populated, not a BM25-only fallback). Exits non-zero on failure.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from onnx_provider import OnnxMiniLMProvider  # noqa: E402

from memweave import MemWeave, MemoryConfig  # noqa: E402
from memweave.config import EmbeddingConfig  # noqa: E402

# Distinct memory facts — each query below should resolve to exactly one of these.
DOCS = {
    "backup.md": (
        "# Database backup\n\n"
        "The palace database is backed up every six hours by a cron job that "
        "copies the sqlite file to a rotating archive directory.\n"
    ),
    "ports.md": (
        "# Docker port registry\n\n"
        "A SQLite registry with a dcup CLI prevents container port conflicts "
        "across projects. Always check the registry before assigning a new port.\n"
    ),
    "embedding.md": (
        "# Offline embeddings\n\n"
        "Memory search runs fully offline using a local all-MiniLM-L6-v2 ONNX "
        "model. No OpenAI, Ollama, or network call happens at embed time.\n"
    ),
    "telegram.md": (
        "# Telegram gateway\n\n"
        "A polling bot bridges Telegram messages to the Claude CLI, deduplicating "
        "updates by update_id and filtering stale messages by age.\n"
    ),
}

# (query, expected top-1 source file basename)
PROBES = [
    ("how often is the database archived", "backup.md"),
    ("avoid container port collisions between projects", "ports.md"),
    ("does memory embedding need an internet connection", "embedding.md"),
    ("bridge chat messages into the claude command line tool", "telegram.md"),
]


async def main() -> int:
    provider = OnnxMiniLMProvider()
    print(f"[poc] embedding model dir: {provider.model_dir}")
    print(f"[poc] provider.model     : {provider.model}")

    with tempfile.TemporaryDirectory(prefix="memweave-poc-") as tmp:
        ws = Path(tmp)
        mem_dir = ws / "memory"
        mem_dir.mkdir(parents=True)
        for name, text in DOCS.items():
            (mem_dir / name).write_text(text)

        config = MemoryConfig(
            workspace_dir=str(ws),
            embedding=EmbeddingConfig(model=provider.model),
            progress=False,
        )

        async with MemWeave(config, embedding_provider=provider) as mem:
            idx = await mem.index()
            print(f"[poc] indexed: {idx.files_indexed} files, {idx.chunks_created} chunks")

            failures = []
            vector_path_seen = False
            for query, expected in PROBES:
                results = await mem.search(query, max_results=3)
                top = results[0] if results else None
                top_base = Path(top.path).name if top else "(none)"
                ok = top is not None and top_base == expected
                if top is not None and top.vector_score is not None:
                    vector_path_seen = True
                vs = f"{top.vector_score:.3f}" if top and top.vector_score is not None else "—"
                ts = f"{top.text_score:.3f}" if top and top.text_score is not None else "—"
                mark = "PASS" if ok else "FAIL"
                print(
                    f"[poc] {mark}  q={query!r:55s} -> {top_base:14s} "
                    f"score={top.score:.3f} vec={vs} bm25={ts}"
                    if top
                    else f"[poc] {mark}  q={query!r} -> (no results)"
                )
                if not ok:
                    failures.append((query, expected, top_base))

    print()
    if failures:
        print(f"[poc] RESULT: FAIL — {len(failures)}/{len(PROBES)} probes missed")
        for q, exp, got in failures:
            print(f"        miss: {q!r} expected {exp}, got {got}")
        return 1
    if not vector_path_seen:
        print("[poc] RESULT: FAIL — vector path never ran (BM25-only); ONNX embeddings "
              "not wired into vector search")
        return 1
    print(f"[poc] RESULT: PASS — {len(PROBES)}/{len(PROBES)} probes top-1, vector path "
          "fired offline. memweave + local ONNX MiniLM works end-to-end.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

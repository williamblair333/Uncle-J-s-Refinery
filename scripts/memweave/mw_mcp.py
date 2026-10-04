#!/usr/bin/env python
"""memweave MCP server: prior-art search over ~/.uncle-j-memory as two tools.

Same read-only query path as mw_search.py, without a Bash round trip. The ONNX
provider loads once per server instead of once per search. Run it under
.venv-memweave (memweave is not installed in the main stack venv).

  memory_search(query, k, min_score)          ranked hits, same scoring as the CLI
  memory_read(path, start_line, end_line)     the context around a hit

memory_read is confined to the corpus: a path that resolves outside the
workspace, through `..` or a symlink, or into the index directory is refused.

Env: MEMWEAVE_WORKSPACE (default ~/.uncle-j-memory).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

WORKSPACE = Path(os.environ.get("MEMWEAVE_WORKSPACE", "~/.uncle-j-memory")).expanduser()
MAX_K = 20
MAX_SNIPPET_CHARS = 1200
MAX_READ_LINES = 400


def _index_db(ws: Path) -> Path:
    return ws / ".memweave" / "index.sqlite"


def _resolve_in_corpus(ws: Path, path: str) -> Path | None:
    root = ws.resolve()
    p = Path(path).expanduser()
    target = (p if p.is_absolute() else root / p).resolve()
    if target != root and root not in target.parents:
        return None
    if (root / ".memweave") in (target, *target.parents):
        return None
    return target


def read_span(ws: Path, path: str, start_line: int = 1, end_line: int | None = None,
              max_lines: int = MAX_READ_LINES) -> dict:
    """Lines start_line..end_line (1-based, inclusive) of a corpus file."""
    target = _resolve_in_corpus(ws, path)
    if target is None:
        return {"error": "path_outside_corpus", "detail": path}
    if not target.is_file():
        return {"error": "file_not_found", "detail": path}
    if start_line < 1 or (end_line is not None and end_line < start_line):
        return {"error": "bad_arguments", "detail": "need 1 <= start_line <= end_line"}
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    want_end = min(end_line or len(lines), len(lines))
    end = min(want_end, start_line + max_lines - 1)
    out = {"path": str(target.relative_to(ws.resolve())), "start_line": start_line,
           "end_line": end, "total_lines": len(lines),
           "text": "".join(lines[start_line - 1:end])}
    if end < want_end:
        out["truncated"] = True
    return out


async def search(ws: Path, query: str, *, searcher, k: int = 5,
                 min_score: float | None = None) -> dict:
    if not query.strip():
        return {"error": "empty_query"}
    if not _index_db(ws).exists():
        return {"error": "no_index",
                "detail": f"no memweave index at {_index_db(ws)}; run sync_memory.sh"}
    k = max(1, min(int(k), MAX_K))
    try:
        hits = await searcher(str(ws), query, k=k, min_score=min_score)
    except Exception as e:  # report, never crash the server
        return {"error": "search_failed", "detail": f"{type(e).__name__}: {e}"}
    results = [{"path": h.path, "score": round(h.score, 4), "start_line": h.start_line,
                "end_line": h.end_line, "snippet": (h.snippet or "").strip()[:MAX_SNIPPET_CHARS]}
               for h in hits]
    return {"count": len(results), "results": results}


def build_server():
    import warnings

    # pydantic-settings warns about FastMCP's own `lifespan` annotation on import.
    warnings.filterwarnings("ignore", message="Field 'lifespan' has an incomplete definition")
    from mcp.server.fastmcp import FastMCP

    import mw_search
    from onnx_provider import OnnxMiniLMProvider

    provider = None

    async def searcher(ws, query, *, k, min_score):
        nonlocal provider
        if provider is None:
            provider = OnnxMiniLMProvider()
        return await mw_search.search_store(ws, query, k=k, min_score=min_score,
                                            provider=provider)

    mcp = FastMCP("memweave", log_level="WARNING", instructions=(
        "Cross-project memory: past session transcripts plus the Obsidian vault mirror "
        "(decisions, priorities, project notes). Search it before non-trivial work — "
        "'have we solved this before?'. Read-only."))

    @mcp.tool(name="memory_search")
    async def _search(query: str, k: int = 5, min_score: float | None = None) -> dict:
        """Search past sessions and vault notes. Returns ranked hits (path, score, line span, snippet)."""
        return await search(WORKSPACE, query, searcher=searcher, k=k, min_score=min_score)

    @mcp.tool(name="memory_read")
    def _read(path: str, start_line: int = 1, end_line: int | None = None) -> dict:
        """Read lines of a memory file returned by memory_search (path as given there). Max 400 lines."""
        return read_span(WORKSPACE, path, start_line, end_line)

    return mcp


if __name__ == "__main__":
    build_server().run()

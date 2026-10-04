"""Tests for the memweave MCP server (scripts/memweave/mw_mcp.py).

The pure layer — corpus path confinement, span reads, search error shapes and
result mapping — runs under any interpreter: memweave is imported only inside
build_server(). The stdio round trip runs only where .venv-memweave and the
ONNX model exist, because that is the interpreter the server is registered with.
"""
import asyncio
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parent.parent
_MW = _REPO / "scripts" / "memweave"
sys.path.insert(0, str(_MW))

import mw_mcp  # noqa: E402


def _ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "memory").mkdir(parents=True)
    (ws / "memory" / "note.md").write_text("".join(f"line {i}\n" for i in range(1, 501)))
    return ws


def _with_index(ws):
    (ws / ".memweave").mkdir()
    (ws / ".memweave" / "index.sqlite").write_bytes(b"")
    return ws


# --- memory_read -----------------------------------------------------------

def test_read_span_relative_path_and_range(tmp_path):
    ws = _ws(tmp_path)
    out = mw_mcp.read_span(ws, "memory/note.md", start_line=3, end_line=5)
    assert out["text"] == "line 3\nline 4\nline 5\n"
    assert (out["start_line"], out["end_line"], out["total_lines"]) == (3, 5, 500)
    assert out["path"] == "memory/note.md"
    assert "truncated" not in out


def test_read_span_accepts_absolute_path_inside_corpus(tmp_path):
    ws = _ws(tmp_path)
    out = mw_mcp.read_span(ws, str(ws / "memory" / "note.md"), start_line=1, end_line=1)
    assert out["text"] == "line 1\n"


def test_read_span_caps_lines(tmp_path):
    ws = _ws(tmp_path)
    out = mw_mcp.read_span(ws, "memory/note.md", max_lines=10)
    assert out["end_line"] == 10
    assert out["truncated"] is True


@pytest.mark.parametrize("bad", ["../outside.md", "/etc/hostname", "memory/../../outside.md"])
def test_read_span_refuses_paths_outside_corpus(tmp_path, bad):
    ws = _ws(tmp_path)
    (tmp_path / "outside.md").write_text("secret")
    assert mw_mcp.read_span(ws, bad)["error"] == "path_outside_corpus"


def test_read_span_refuses_symlink_out_of_corpus(tmp_path):
    ws = _ws(tmp_path)
    (tmp_path / "outside.md").write_text("secret")
    (ws / "memory" / "link.md").symlink_to(tmp_path / "outside.md")
    assert mw_mcp.read_span(ws, "memory/link.md")["error"] == "path_outside_corpus"


def test_read_span_refuses_index_internals(tmp_path):
    ws = _with_index(_ws(tmp_path))
    assert mw_mcp.read_span(ws, ".memweave/index.sqlite")["error"] == "path_outside_corpus"


def test_read_span_missing_file(tmp_path):
    ws = _ws(tmp_path)
    assert mw_mcp.read_span(ws, "memory/nope.md")["error"] == "file_not_found"


def test_read_span_bad_range(tmp_path):
    ws = _ws(tmp_path)
    assert mw_mcp.read_span(ws, "memory/note.md", start_line=9, end_line=3)["error"] == "bad_arguments"


# --- memory_search ---------------------------------------------------------

def _hit(path, score, snippet="text"):
    return SimpleNamespace(path=path, score=score, start_line=1, end_line=9, snippet=snippet,
                           vector_score=0.5, text_score=None)


def _search(ws, query, searcher, **kw):
    return asyncio.run(mw_mcp.search(ws, query, searcher=searcher, **kw))


def test_search_empty_query_never_calls_searcher(tmp_path):
    called = []

    async def searcher(*a, **k):
        called.append(1)
        return []

    out = _search(_with_index(_ws(tmp_path)), "   ", searcher)
    assert out["error"] == "empty_query"
    assert called == []


def test_search_missing_index_is_structured(tmp_path):
    async def searcher(*a, **k):
        raise AssertionError("must not search without an index")

    out = _search(_ws(tmp_path), "anything", searcher)
    assert out["error"] == "no_index"
    assert "sync_memory.sh" in out["detail"]


def test_search_maps_results(tmp_path):
    async def searcher(ws, query, *, k, min_score):
        assert (query, k, min_score) == ("why", 3, 0.2)
        return [_hit("memory/a.md", 0.71234), _hit("memory/b.md", 0.5)]

    out = _search(_with_index(_ws(tmp_path)), "why", searcher, k=3, min_score=0.2)
    assert out["count"] == 2
    first = out["results"][0]
    assert first == {"path": "memory/a.md", "score": 0.7123, "start_line": 1,
                     "end_line": 9, "snippet": "text"}


def test_search_clamps_k(tmp_path):
    seen = {}

    async def searcher(ws, query, *, k, min_score):
        seen["k"] = k
        return []

    ws = _with_index(_ws(tmp_path))
    _search(ws, "q", searcher, k=500)
    assert seen["k"] == mw_mcp.MAX_K
    _search(ws, "q", searcher, k=0)
    assert seen["k"] == 1


def test_search_truncates_long_snippets(tmp_path):
    async def searcher(*a, **k):
        return [_hit("memory/a.md", 0.9, snippet="x" * 5000)]

    out = _search(_with_index(_ws(tmp_path)), "q", searcher)
    assert len(out["results"][0]["snippet"]) == mw_mcp.MAX_SNIPPET_CHARS


def test_search_failure_is_structured(tmp_path):
    async def searcher(*a, **k):
        raise RuntimeError("database is locked")

    out = _search(_with_index(_ws(tmp_path)), "q", searcher)
    assert out["error"] == "search_failed"
    assert "database is locked" in out["detail"]


def test_no_hits_is_not_an_error(tmp_path):
    async def searcher(*a, **k):
        return []

    out = _search(_with_index(_ws(tmp_path)), "q", searcher)
    assert out == {"count": 0, "results": []}


# --- stdio round trip under the real interpreter ---------------------------

_MW_PY = _REPO / ".venv-memweave" / "bin" / "python"
_MODEL = Path(os.environ.get("MEMWEAVE_ONNX_MODEL_DIR",
                             os.path.expanduser("~/.code-index/models/all-MiniLM-L6-v2")))


@pytest.mark.skipif(not _MW_PY.exists() or not (_MODEL / "model.onnx").exists(),
                    reason="no .venv-memweave or ONNX model on this host")
def test_stdio_round_trip_indexes_searches_and_reads(tmp_path):
    ws = tmp_path / "ws"
    (ws / "memory").mkdir(parents=True)
    (ws / "memory" / "fact.md").write_text(
        "# Backup policy\n\nThe database is archived every six hours by a scheduled job.\n")
    (ws / "memory" / "other.md").write_text("# Ports\n\nThe registry prevents port conflicts.\n")
    script = textwrap.dedent(f"""
        import asyncio, json, sys
        sys.path.insert(0, {str(_MW)!r})
        from onnx_provider import OnnxMiniLMProvider
        from memweave import MemWeave, MemoryConfig
        from memweave.config import EmbeddingConfig
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def main():
            p = OnnxMiniLMProvider()
            cfg = MemoryConfig(workspace_dir={str(ws)!r},
                               embedding=EmbeddingConfig(model=p.model), progress=False)
            async with MemWeave(cfg, embedding_provider=p) as mem:
                await mem.index()
            params = StdioServerParameters(command=sys.executable,
                args=[{str(_MW / "mw_mcp.py")!r}], env={{"MEMWEAVE_WORKSPACE": {str(ws)!r}}})
            async with stdio_client(params) as (r, w):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    names = sorted(t.name for t in (await s.list_tools()).tools)
                    hit = await s.call_tool("memory_search",
                        {{"query": "how often is the database backed up", "k": 2}})
                    found = json.loads(hit.content[0].text)
                    read = await s.call_tool("memory_read",
                        {{"path": found["results"][0]["path"], "start_line": 1, "end_line": 1}})
                    print(json.dumps({{"names": names, "top": found["results"][0]["path"],
                                       "read": json.loads(read.content[0].text)}}))
        asyncio.run(main())
    """)
    proc = subprocess.run([str(_MW_PY), "-c", script], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["names"] == ["memory_read", "memory_search"]
    assert Path(out["top"]).name == "fact.md"
    assert out["read"]["text"] == "# Backup policy\n"

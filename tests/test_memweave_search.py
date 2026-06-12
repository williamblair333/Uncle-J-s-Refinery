"""Tests for the read-only memory search CLI (scripts/memweave/mw_search.py).

A model-gated integration test builds a tiny workspace, indexes it once, then
exercises the query-only search_store() path (no re-index). A pure test covers
the missing-store guard via subprocess.
"""
import asyncio
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("onnxruntime")
pytest.importorskip("tokenizers")
pytest.importorskip("numpy")

_REPO = Path(__file__).resolve().parent.parent
_MW = _REPO / "scripts" / "memweave"
_MODEL_DIR = Path(os.environ.get(
    "MEMWEAVE_ONNX_MODEL_DIR",
    os.path.expanduser("~/.code-index/models/all-MiniLM-L6-v2")))

_model_missing = not (_MODEL_DIR / "model.onnx").exists()
_memweave_missing = importlib.util.find_spec("memweave") is None

sys.path.insert(0, str(_MW))


@pytest.mark.skipif(_model_missing or _memweave_missing,
                    reason="ONNX model or memweave package not present")
def test_search_store_finds_indexed_doc():
    """search_store() (query-only) retrieves a doc from a freshly-indexed workspace
    without calling index() itself."""
    import mw_search
    from onnx_provider import OnnxMiniLMProvider
    from memweave import MemWeave, MemoryConfig
    from memweave.config import EmbeddingConfig

    with tempfile.TemporaryDirectory(prefix="mw-search-test-") as tmp:
        ws = Path(tmp)
        (ws / "memory").mkdir(parents=True)
        (ws / "memory" / "fact.md").write_text(
            "# Backup policy\n\nThe database is archived every six hours to a "
            "rotating directory by a scheduled job.\n")
        (ws / "memory" / "other.md").write_text(
            "# Ports\n\nThe dcup registry prevents container port conflicts.\n")

        async def _build_then_query():
            provider = OnnxMiniLMProvider()
            cfg = MemoryConfig(workspace_dir=str(ws),
                               embedding=EmbeddingConfig(model=provider.model), progress=False)
            async with MemWeave(cfg, embedding_provider=provider) as mem:
                await mem.index()
            # query-only path under test:
            return await mw_search.search_store(str(ws), "how often is the database backed up", k=2)

        results = asyncio.run(_build_then_query())
        assert results, "expected at least one hit"
        assert Path(results[0].path).name == "fact.md"


def test_cli_missing_store_exits_nonzero():
    """The CLI guards a missing index with a clear message + nonzero exit."""
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            [sys.executable, str(_MW / "mw_search.py"), "anything", "--workspace", tmp],
            capture_output=True, text=True)
    assert proc.returncode == 1
    assert "no memweave index" in proc.stderr


def test_cli_empty_query_exits_2():
    proc = subprocess.run(
        [sys.executable, str(_MW / "mw_search.py"), "   "],
        capture_output=True, text=True)
    assert proc.returncode == 2

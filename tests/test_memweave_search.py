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


def _memweave_python() -> Path | None:
    """Interpreter that can actually import memweave, or None.

    NOT `sys.executable`. memweave lives in its own virtualenv — this repo has
    two, `.venv` for the MCP stack and `.venv-memweave` for the search CLI, and
    CLAUDE.md documents invoking mw_search.py with the latter. Running the CLI
    under the pytest interpreter raised ModuleNotFoundError before it reached
    any argument parsing, so both CLI tests below asserted against a traceback
    rather than against the guards they name.

    `bin` vs `Scripts` because docs/WINDOWS-PORT.md records the layout split
    (and records `uv sync` destroying the compat symlink, so do not rely on it).
    """
    for sub in ("bin/python", "Scripts/python.exe"):
        candidate = _REPO / ".venv-memweave" / sub
        if candidate.exists():
            return candidate
    return None


_MW_PYTHON = _memweave_python()
_requires_mw_cli = pytest.mark.skipif(
    _MW_PYTHON is None,
    reason="no .venv-memweave interpreter — memweave CLI not installed on this host",
)


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


@_requires_mw_cli
def test_cli_missing_store_exits_nonzero():
    """The CLI guards a missing index with a clear message + nonzero exit.

    CLAUDE.md tells every session to read a nonzero exit here as 'fall back to
    the transcript', so the exit code is a contract, not an implementation
    detail. Pointing at an empty workspace must not create one — the CLI is
    documented read-only.
    """
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            [str(_MW_PYTHON), str(_MW / "mw_search.py"), "anything", "--workspace", tmp],
            capture_output=True, text=True)
        assert not (Path(tmp) / ".memweave").exists(), "search must not write an index"
    assert proc.returncode == 1
    assert "no memweave index" in proc.stderr


@_requires_mw_cli
def test_cli_empty_query_exits_2():
    """2, not 1: usage error is distinct from a missing store, because the
    documented fallback differs — fix the query vs. fall back to the transcript."""
    proc = subprocess.run(
        [str(_MW_PYTHON), str(_MW / "mw_search.py"), "   "],
        capture_output=True, text=True)
    assert proc.returncode == 2

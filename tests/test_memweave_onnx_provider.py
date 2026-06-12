"""Tests for the offline ONNX embedding provider (scripts/memweave/onnx_provider.py).

These are real integration tests against the on-disk all-MiniLM-L6-v2 model;
they skip when the model is absent. Run under any interpreter that has
onnxruntime + tokenizers + numpy (e.g. the project .venv or .venv-memweave):

    .venv-memweave/bin/python -m pytest tests/test_memweave_onnx_provider.py -v

The pad-invariance test is the correctness guard for masked mean-pooling: a bug
that pools over pad tokens would make a short text's vector depend on its
batch-mates' lengths, and this test would fail.
"""
import asyncio
import math
import os
import sys
from pathlib import Path

import pytest

# These run only where the ONNX runtime stack exists (the 3.12 memweave venv).
# In the project venv / CI without these deps, skip cleanly instead of erroring
# at collection time.
pytest.importorskip("onnxruntime")
pytest.importorskip("tokenizers")
pytest.importorskip("numpy")

_REPO = Path(__file__).resolve().parent.parent
_MODEL_DIR = Path(
    os.environ.get(
        "MEMWEAVE_ONNX_MODEL_DIR",
        os.path.expanduser("~/.code-index/models/all-MiniLM-L6-v2"),
    )
)

pytestmark = pytest.mark.skipif(
    not (_MODEL_DIR / "model.onnx").exists() or not (_MODEL_DIR / "vocab.txt").exists(),
    reason=f"local all-MiniLM-L6-v2 ONNX model not present at {_MODEL_DIR}",
)

sys.path.insert(0, str(_REPO / "scripts" / "memweave"))


def _provider():
    from onnx_provider import OnnxMiniLMProvider

    return OnnxMiniLMProvider()


def _cos(a, b):
    # Vectors are unit-normalized, so dot == cosine.
    return sum(x * y for x, y in zip(a, b))


# One provider for the whole module — ONNX session construction is the slow part.
@pytest.fixture(scope="module")
def provider():
    return _provider()


def test_embed_query_dim_and_unit_norm(provider):
    v = asyncio.run(provider.embed_query("deployment process for the refinery"))
    assert len(v) == 384
    norm = math.sqrt(sum(x * x for x in v))
    assert abs(norm - 1.0) < 1e-4


def test_embed_batch_shape(provider):
    vs = asyncio.run(provider.embed_batch(["alpha text here", "beta longer text", "gamma"]))
    assert len(vs) == 3
    assert all(len(v) == 384 for v in vs)


def test_deterministic(provider):
    a = asyncio.run(provider.embed_query("the quick brown fox jumps"))
    b = asyncio.run(provider.embed_query("the quick brown fox jumps"))
    assert a == b


def test_pad_invariance(provider):
    """A short text's embedding must not change when batched with a much longer
    text that forces heavy right-padding. This catches masked-pooling bugs
    (pooling over pad tokens) — the #1 way to get plausible-but-wrong vectors."""
    short = "back up the database nightly"
    long = (
        "this is a deliberately much longer document about unrelated topics "
        "such as port registries, cron scheduling, healthcheck probes, and "
        "the migration of a memory backend from one vector store to another, "
        "written to force a large amount of padding on the short sibling row"
    )
    alone = asyncio.run(provider.embed_query(short))
    batched = asyncio.run(provider.embed_batch([short, long]))[0]
    # Cosine must be ~1.0; allow tiny float drift from batched matmul ordering.
    assert _cos(alone, batched) > 0.9999


def test_semantic_ordering(provider):
    q = asyncio.run(provider.embed_query("how do I back up the database"))
    near = asyncio.run(provider.embed_query("steps to create a database backup"))
    far = asyncio.run(provider.embed_query("the cat sat on a warm windowsill"))
    assert _cos(q, near) > _cos(q, far)


def test_empty_query_raises(provider):
    with pytest.raises(ValueError):
        asyncio.run(provider.embed_query("   "))


def test_model_property(provider):
    assert provider.model == "onnx/all-MiniLM-L6-v2"

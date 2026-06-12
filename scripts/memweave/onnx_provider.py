"""Offline ONNX embedding provider for memweave.

Wraps the on-disk all-MiniLM-L6-v2 ONNX model so memweave runs fully offline —
no litellm / OpenAI / Ollama / network at embed time. Implements memweave's
EmbeddingProvider protocol (async embed_query / embed_batch + a `model`
property), returning L2-normalized 384-dim vectors so cosine == dot, matching
memweave's normalization contract.

Inject via:
    from memweave import MemWeave, MemoryConfig
    MemWeave(config, embedding_provider=OnnxMiniLMProvider())

Model dir defaults to the jcodemunch canary model and is overridable via the
MEMWEAVE_ONNX_MODEL_DIR env var. The dir must contain model.onnx + vocab.txt.

Correctness contract (guarded by tests/test_memweave_onnx_provider.py):
  - masked mean-pooling over real (non-pad) tokens only -> a short text embedded
    alone equals the same text embedded in a padded batch (pad-invariance);
  - L2-normalized output (unit norm);
  - deterministic;
  - semantically ordered (related text scores above unrelated).
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import BertWordPieceTokenizer

DEFAULT_MODEL_DIR = os.environ.get(
    "MEMWEAVE_ONNX_MODEL_DIR",
    os.path.expanduser("~/.code-index/models/all-MiniLM-L6-v2"),
)
MODEL_NAME = "onnx/all-MiniLM-L6-v2"
EMBED_DIM = 384
_MAX_SEQ = 256


class OnnxMiniLMProvider:
    """memweave EmbeddingProvider backed by a local all-MiniLM-L6-v2 ONNX model.

    Tokenizes with the model's WordPiece vocab, runs the ONNX graph on CPU,
    masked-mean-pools the last hidden state over real (non-pad) tokens, then
    L2-normalizes to unit length.
    """

    def __init__(self, model_dir: str | Path = DEFAULT_MODEL_DIR, *, max_seq: int = _MAX_SEQ):
        model_dir = Path(model_dir).expanduser()
        onnx_path = model_dir / "model.onnx"
        vocab_path = model_dir / "vocab.txt"
        if not onnx_path.exists() or not vocab_path.exists():
            raise FileNotFoundError(
                f"ONNX model/vocab not found in {model_dir} (need model.onnx + vocab.txt). "
                f"Set MEMWEAVE_ONNX_MODEL_DIR to override."
            )
        self.model_dir = model_dir
        self._max_seq = max_seq
        # Single CPU session, reused across calls. Thread count left to ORT default.
        self._session = ort.InferenceSession(
            str(onnx_path), providers=["CPUExecutionProvider"]
        )
        # all-MiniLM-L6-v2 is uncased; WordPiece tokenizer adds [CLS]/[SEP].
        self._tok = BertWordPieceTokenizer(str(vocab_path), lowercase=True)
        self._tok.enable_truncation(max_length=max_seq)

    @property
    def model(self) -> str:
        return MODEL_NAME

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        encs = self._tok.encode_batch(texts)
        maxlen = max(len(e.ids) for e in encs)
        n = len(encs)
        input_ids = np.zeros((n, maxlen), dtype=np.int64)
        attn = np.zeros((n, maxlen), dtype=np.int64)
        ttype = np.zeros((n, maxlen), dtype=np.int64)
        for i, e in enumerate(encs):
            length = len(e.ids)
            input_ids[i, :length] = e.ids
            attn[i, :length] = e.attention_mask
            ttype[i, :length] = e.type_ids
        last_hidden = self._session.run(
            ["last_hidden_state"],
            {"input_ids": input_ids, "attention_mask": attn, "token_type_ids": ttype},
        )[0]  # [n, seq, 384]
        # Masked mean-pool over real tokens only — pad rows are zeroed by the mask,
        # so a text's vector is independent of any padding added for its batch-mates.
        mask = attn[:, :, None].astype(np.float32)  # [n, seq, 1]
        summed = (last_hidden * mask).sum(axis=1)  # [n, 384]
        counts = np.clip(mask.sum(axis=1), 1e-9, None)  # [n, 1]
        mean = summed / counts
        norms = np.clip(np.linalg.norm(mean, axis=1, keepdims=True), 1e-12, None)
        unit = mean / norms
        return unit.astype(np.float32).tolist()

    async def embed_query(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise ValueError("embed_query received empty text")
        return self._embed_sync([text])[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._embed_sync(list(texts))

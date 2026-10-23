"""Local rail: batch jobs call the local model (ask_local's backend) with a content-hash cache.

Phase 3 of the improvement program, scoped down (2026-10-23): ask_local already IS the
local endpoint (Heretic on llama-server, or Ollama, per config/ask_local.env), so the
"Ollama endpoint + hardware-detect model select" half is done by the lineup work. What
was left is batch jobs running local-first without paying twice for the same input.

    from scripts.local_rail import Rail
    rail = Rail()                       # backend/model from config/ask_local.env
    res = rail.chat("job_name", prompt, system=..., max_tokens=...)
    # res: {"text", "model", "tokens_in", "tokens_out", "cached": bool} or {"error", ...}

The cache key is sha256 over (backend, model, system, prompt, max_tokens, temperature,
CACHE_VERSION). Same input → same file → no model call. Only successful answers are
cached; errors never are, so a down backend is retried next run. Writes are atomic
(tmp + os.replace), so an interrupted run never leaves a half-written entry.

The default temperature is 0: a cached answer should be the answer the model gives.
Cache lives in state/local-rail-cache/ (gitignored); delete it to force fresh calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = REPO / "state" / "local-rail-cache"
CACHE_VERSION = 1


def cache_key(*, backend: str, model: str, system: str | None, prompt: str,
              max_tokens: int, temperature: float | None) -> str:
    blob = json.dumps({"v": CACHE_VERSION, "backend": backend, "model": model,
                       "system": system or "", "prompt": prompt,
                       "max_tokens": max_tokens, "temperature": temperature},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Rail:
    """A LocalClient plus a content-hash cache. `client` is injectable for tests."""

    def __init__(self, client=None, cache_dir: Path | None = DEFAULT_CACHE):
        if client is None:
            import httpx

            from scripts.ask_local.server import OLLAMA_URL, LocalClient
            client = LocalClient(httpx.Client(base_url=OLLAMA_URL))
        self.client = client
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None

    @property
    def http(self):
        return self.client.http

    def _path(self, key: str) -> Path | None:
        return self.cache_dir / key[:2] / f"{key}.json" if self.cache_dir else None

    def chat(self, job: str, prompt: str, *, system: str | None = None,
             max_tokens: int = 1024, temperature: float | None = 0,
             use_cache: bool = True) -> dict:
        key = cache_key(backend=self.client.backend, model=self.client.model,
                        system=system, prompt=prompt, max_tokens=max_tokens,
                        temperature=temperature)
        path = self._path(key) if use_cache else None
        if path is not None and path.is_file():
            try:
                hit = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(hit, dict) and isinstance(hit.get("text"), str):
                    return {**hit, "cached": True}
            except (OSError, ValueError):
                pass  # unreadable entry: fall through and replace it

        res = self.client.chat(job, prompt, system=system, max_tokens=max_tokens,
                               temperature=temperature, input_chars=len(prompt))
        if "error" in res or path is None:
            return {**res, "cached": False}
        entry = {k: res[k] for k in ("text", "model", "tokens_in", "tokens_out") if k in res}
        entry["job"] = job
        tmp = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False)
            os.replace(tmp, path)
            tmp = None
        except (OSError, TypeError, ValueError):
            pass  # a cache that can't be written must never fail the job
        finally:
            if tmp is not None:
                Path(tmp).unlink(missing_ok=True)
        return {**res, "cached": False}

"""Chatterbox Nano text-to-speech over HTTP, CPU only. Runs inside docker/chatterbox.

  GET  /health            {"model": "chatterbox-nano", "device": "cpu", "voices": [...]}
  GET  /v1/voices         {"voices": ["default", <name of each /voices/*.wav>]}
  POST /v1/audio/speech   {"input": "text", "voice": "default"|<name>} -> audio/wav

The body follows OpenAI's /v1/audio/speech shape (extra fields are ignored). A voice is a
5-20 s reference clip dropped into the voices directory as <name>.wav; its conditioning is
computed once and cached until the file changes. Long input is split into sentences and
generated one at a time, because the model drifts on long single passes. One request runs
at a time; the CPU is the bottleneck anyway.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_CHARS = int(os.environ.get("TTS_MAX_CHARS", "4000"))
VOICE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str, max_len: int = 300) -> list[str]:
    """Split text into sentences; a sentence over max_len chars is cut at commas, then words."""
    text = " ".join(text.split())
    out: list[str] = []
    for sent in _SENTENCE_END.split(text):
        sent = sent.strip()
        while len(sent) > max_len:
            cut = sent.rfind(", ", 0, max_len - 1) + 1  # keep the comma; 0 if none
            if cut <= 0:
                cut = sent.rfind(" ", 0, max_len + 1)
            if cut <= 0:
                cut = max_len
            out.append(sent[:cut].strip())
            sent = sent[cut:].strip()
        if sent:
            out.append(sent)
    return out


def resolve_voice(name: str | None, voices_dir: Path) -> Path | None:
    """Map a voice name to its reference wav; None means the model's built-in voice.

    Raises ValueError for a malformed name and FileNotFoundError for an unknown one.
    """
    if name in (None, "", "default"):
        return None
    if not isinstance(name, str) or not VOICE_NAME.match(name):
        raise ValueError(f"bad voice name: {name!r}")
    path = voices_dir / f"{name}.wav"
    if path.resolve().parent != voices_dir.resolve() or not path.is_file():
        raise FileNotFoundError(f"no voice named {name!r}")
    return path


def list_voices(voices_dir: Path) -> list[str]:
    names = sorted(p.stem for p in voices_dir.glob("*.wav")) if voices_dir.is_dir() else []
    return ["default"] + [n for n in names if VOICE_NAME.match(n)]


def to_wav_bytes(samples, sample_rate: int) -> bytes:
    """Float samples in [-1, 1] (any 1-D sequence or numpy array) -> 16-bit mono WAV bytes."""
    import numpy as np

    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class Synth:
    """Wraps the model: per-voice conditioning cache, sentence loop, one job at a time."""

    def __init__(self, model, voices_dir: Path, gap_s: float = 0.15):
        self.model = model
        self.voices_dir = voices_dir
        self.gap_s = gap_s
        self.lock = threading.Lock()
        self.default_conds = model.conds
        self._cache: dict[str, tuple[float, object]] = {}

    def _use_voice(self, path: Path | None) -> None:
        if path is None:
            self.model.conds = self.default_conds
            return
        mtime = path.stat().st_mtime
        hit = self._cache.get(path.name)
        if hit is None or hit[0] != mtime:
            self.model.prepare_conditionals(str(path))
            hit = (mtime, self.model.conds)
            self._cache[path.name] = hit
        self.model.conds = hit[1]

    def speak(self, text: str, voice: str | None) -> bytes:
        import numpy as np

        path = resolve_voice(voice, self.voices_dir)
        parts = split_sentences(text)
        if not parts:
            raise ValueError("input is empty")
        sr = self.model.sr
        gap = np.zeros(int(sr * self.gap_s), dtype=np.float32)
        with self.lock:
            self._use_voice(path)
            chunks = []
            for i, sent in enumerate(parts):
                wav = self.model.generate(sent)
                chunks.append(np.asarray(wav, dtype=np.float32).reshape(-1))
                if i < len(parts) - 1:
                    chunks.append(gap)
        return to_wav_bytes(np.concatenate(chunks), sr)


def make_handler(synth: Synth, info: dict):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, body: dict) -> None:
            data = json.dumps(body, separators=(",", ":")).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                self._json(200, {**info, "voices": list_voices(synth.voices_dir)})
            elif self.path == "/v1/voices":
                self._json(200, {"voices": list_voices(synth.voices_dir)})
            else:
                self._json(404, {"error": "not_found"})

        def do_POST(self):  # noqa: N802
            if self.path != "/v1/audio/speech":
                self._json(404, {"error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                text = body.get("input")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("'input' must be a non-empty string")
                if len(text) > MAX_CHARS:
                    raise ValueError(f"'input' is over {MAX_CHARS} characters")
                fmt = body.get("response_format", "wav")
                if fmt != "wav":
                    raise ValueError("only response_format 'wav' is supported")
                t0 = time.monotonic()
                audio = synth.speak(text, body.get("voice"))
                took = time.monotonic() - t0
            except FileNotFoundError as e:
                self._json(404, {"error": str(e)})
                return
            except (ValueError, json.JSONDecodeError) as e:
                self._json(400, {"error": str(e)})
                return
            except Exception as e:  # model failure: report it, keep serving
                self._json(500, {"error": f"{type(e).__name__}: {e}"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(audio)))
            self.send_header("X-Generation-Seconds", f"{took:.2f}")
            self.end_headers()
            self.wfile.write(audio)

        def log_message(self, fmt, *args):
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    return Handler


def main() -> None:
    import torch
    from chatterbox.tts_turbo import ChatterboxTurboTTS

    threads = int(os.environ.get("TTS_THREADS", "0"))
    if threads > 0:
        torch.set_num_threads(threads)
    model_dir = os.environ.get("TTS_MODEL_DIR", "/models")
    voices_dir = Path(os.environ.get("TTS_VOICES_DIR", "/voices"))
    t0 = time.monotonic()
    model = ChatterboxTurboTTS.from_local(model_dir, device="cpu", nano=True)
    print(f"loaded chatterbox-nano in {time.monotonic() - t0:.1f}s, "
          f"{torch.get_num_threads()} threads", flush=True)
    info = {"model": "chatterbox-nano", "device": "cpu", "sample_rate": model.sr}
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))),
                                 make_handler(Synth(model, voices_dir), info))
    server.serve_forever()


if __name__ == "__main__":
    main()

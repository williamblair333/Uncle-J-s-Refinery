"""Local speech services: scripts/speech.sh routing and docker/chatterbox/server.py logic.

speech.sh runs against stub dcup/docker on PATH, so no container is touched. server.py is
imported without torch or chatterbox (they're only imported in main()); a fake model stands
in for Chatterbox.
"""
import importlib.util
import io
import json
import os
import subprocess
import threading
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib import error, request

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parent.parent
SCRIPT = _REPO / "scripts" / "speech.sh"
COMPOSE = {"whisper": _REPO / "docker" / "whisper" / "compose.yaml",
           "tts": _REPO / "docker" / "chatterbox" / "compose.yaml"}

_spec = importlib.util.spec_from_file_location("chatterbox_server", _REPO / "docker" / "chatterbox" / "server.py")
srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srv)


# --- speech.sh ---------------------------------------------------------------------------

def _run(tmp_path, args, dcup=True, check=True):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    for name in ["docker"] + (["dcup"] if dcup else []):
        stub = bin_dir / name
        stub.write_text(f'#!/usr/bin/env bash\necho "{name} $*" >> {log}\n')
        stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin",
           "DCUP_FALLBACK": str(tmp_path / "no-dcup")}
    proc = subprocess.run(["bash", str(SCRIPT), *args], env=env, check=check,
                          capture_output=True, text=True)
    return proc, (log.read_text().splitlines() if log.exists() else [])


@pytest.mark.parametrize("svc", ["whisper", "tts"])
def test_up_goes_through_dcup(tmp_path, svc):
    assert _run(tmp_path, [svc, "up", "-d"])[1] == [f"dcup up -f {COMPOSE[svc]} -d"]


@pytest.mark.parametrize("svc", ["whisper", "tts"])
def test_other_subcommands_use_docker_compose(tmp_path, svc):
    assert _run(tmp_path, [svc, "logs", "--tail", "5"])[1] == [
        f"docker compose -f {COMPOSE[svc]} logs --tail 5"]


def test_up_without_dcup_falls_back_to_compose(tmp_path):
    assert _run(tmp_path, ["tts", "up", "-d"], dcup=False)[1] == [
        f"docker compose -f {COMPOSE['tts']} up -d"]


def test_unknown_service_is_refused_and_runs_nothing(tmp_path):
    proc, calls = _run(tmp_path, ["ollama", "up", "-d"], check=False)
    assert proc.returncode == 2 and "usage" in proc.stderr and calls == []


def test_compose_files_bind_loopback_and_reserve_no_gpu():
    for path in COMPOSE.values():
        text = path.read_text()
        assert '"127.0.0.1:' in text
        assert "nvidia" not in text and "gpu" not in text.split("#")[0]


# --- server.py helpers -------------------------------------------------------------------

def test_split_sentences_keeps_short_text_whole():
    assert srv.split_sentences("  Hello   there.  ") == ["Hello there."]


def test_split_sentences_splits_on_sentence_ends():
    assert srv.split_sentences("One. Two! Three? Four") == ["One.", "Two!", "Three?", "Four"]


def test_split_sentences_cuts_long_sentence_at_comma_then_space():
    long = ", ".join(["word " * 10] * 5).strip()
    parts = srv.split_sentences(long, max_len=80)
    assert all(len(p) <= 80 for p in parts)
    assert " ".join(parts).split() == long.split()


def test_split_sentences_hard_cuts_a_run_without_spaces():
    assert srv.split_sentences("x" * 25, max_len=10) == ["x" * 10, "x" * 10, "x" * 5]


def test_resolve_voice_default_is_builtin(tmp_path):
    for name in (None, "", "default"):
        assert srv.resolve_voice(name, tmp_path) is None


def test_resolve_voice_finds_named_wav(tmp_path):
    (tmp_path / "lincoln.wav").write_bytes(b"x")
    assert srv.resolve_voice("lincoln", tmp_path) == tmp_path / "lincoln.wav"


@pytest.mark.parametrize("bad", ["../etc/passwd", "a/b", ".hidden", "x" * 65, 7])
def test_resolve_voice_rejects_bad_names(tmp_path, bad):
    with pytest.raises(ValueError):
        srv.resolve_voice(bad, tmp_path)


def test_resolve_voice_unknown_name(tmp_path):
    with pytest.raises(FileNotFoundError):
        srv.resolve_voice("nobody", tmp_path)


def test_list_voices(tmp_path):
    for n in ("b.wav", "a.wav", "notes.txt"):
        (tmp_path / n).write_bytes(b"x")
    assert srv.list_voices(tmp_path) == ["default", "a", "b"]
    assert srv.list_voices(tmp_path / "missing") == ["default"]


def test_to_wav_bytes_clips_and_encodes_16bit_mono():
    data = srv.to_wav_bytes(np.array([0.0, 2.0, -2.0, 0.5]), 24000)
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 24000, 4)
        frames = np.frombuffer(w.readframes(4), dtype="<i2")
    assert list(frames) == [0, 32767, -32767, 16383]


# --- Synth + HTTP with a fake model ------------------------------------------------------

class FakeModel:
    sr = 1000

    def __init__(self):
        self.conds = "builtin"
        self.prepared = []
        self.generated = []

    def prepare_conditionals(self, path):
        self.prepared.append(path)
        self.conds = f"conds:{Path(path).name}"

    def generate(self, text):
        self.generated.append((text, self.conds))
        return np.full((1, 100), 0.1, dtype=np.float32)


def test_synth_caches_voice_conditioning_and_restores_default(tmp_path):
    (tmp_path / "v.wav").write_bytes(b"x")
    model = FakeModel()
    synth = srv.Synth(model, tmp_path, gap_s=0.01)
    synth.speak("One. Two.", "v")
    synth.speak("Three.", "v")
    synth.speak("Four.", None)
    assert model.prepared == [str(tmp_path / "v.wav")]
    assert [c for _, c in model.generated] == ["conds:v.wav"] * 3 + ["builtin"]


def test_synth_output_has_gaps_between_sentences(tmp_path):
    synth = srv.Synth(FakeModel(), tmp_path, gap_s=0.01)
    with wave.open(io.BytesIO(synth.speak("A. B. C.", None))) as w:
        assert w.getnframes() == 3 * 100 + 2 * 10


@pytest.fixture
def server(tmp_path):
    (tmp_path / "v.wav").write_bytes(b"x")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_handler(
        srv.Synth(FakeModel(), tmp_path, gap_s=0.0), {"model": "fake"}))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _post(url, body):
    req = request.Request(url + "/v1/audio/speech", data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req) as r:
            return r.status, r.headers.get("Content-Type"), r.read()
    except error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), e.read()


def test_http_speech_returns_wav(server):
    code, ctype, body = _post(server, {"input": "Hello.", "voice": "v", "model": "ignored"})
    assert (code, ctype) == (200, "audio/wav") and body[:4] == b"RIFF"


@pytest.mark.parametrize("body,code", [
    ({}, 400), ({"input": "   "}, 400), ({"input": 5}, 400),
    ({"input": "hi", "response_format": "mp3"}, 400),
    ({"input": "hi", "voice": "../x"}, 400), ({"input": "hi", "voice": "nobody"}, 404),
    ({"input": "x" * (srv.MAX_CHARS + 1)}, 400),
])
def test_http_speech_rejects_bad_requests(server, body, code):
    status, ctype, data = _post(server, body)
    assert status == code and ctype == "application/json" and "error" in json.loads(data)


def test_http_health_and_voices(server):
    with request.urlopen(server + "/health") as r:
        assert json.loads(r.read()) == {"model": "fake", "voices": ["default", "v"]}
    with request.urlopen(server + "/v1/voices") as r:
        assert json.loads(r.read()) == {"voices": ["default", "v"]}

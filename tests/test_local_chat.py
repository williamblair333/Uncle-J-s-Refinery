import http.client
import importlib.util
import json
import socket
import urllib.error
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("local_chat_server", REPO / "scripts" / "local_chat" / "server.py")
lc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lc)


def _resolve_to(monkeypatch, *addrs):
    infos = [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 80))
             for a in addrs]
    monkeypatch.setattr(lc.socket, "getaddrinfo", lambda *a, **k: infos)


@pytest.mark.parametrize("addr", ["127.0.0.1", "10.0.0.100", "192.168.1.5", "172.16.0.1",
                                  "169.254.169.254", "::1", "fe80::1", "100.94.95.50", "0.0.0.0"])
def test_public_url_refuses_local_addresses(monkeypatch, addr):
    _resolve_to(monkeypatch, addr)
    assert not lc.public_url("http://example.com/")


def test_public_url_refuses_mixed_answers(monkeypatch):
    _resolve_to(monkeypatch, "93.184.215.14", "127.0.0.1")
    assert not lc.public_url("https://example.com/")


def test_public_url_accepts_public(monkeypatch):
    _resolve_to(monkeypatch, "93.184.215.14")
    assert lc.public_url("https://example.com/page")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/", "gopher://x/", "http:///nohost", "not a url"])
def test_public_url_refuses_other_schemes(url):
    assert not lc.public_url(url)


def test_redirect_to_local_is_refused(monkeypatch):
    _resolve_to(monkeypatch, "127.0.0.1")
    h = lc._PublicRedirects()
    with pytest.raises(lc.urllib.error.URLError):
        h.redirect_request(None, None, 302, "Found", {}, "http://localhost:3000/")


def test_fetch_page_skips_non_public_without_network(monkeypatch):
    monkeypatch.setattr(lc, "public_url", lambda u: False)
    monkeypatch.setattr(lc._OPENER, "open", lambda *a, **k: pytest.fail("must not fetch"))
    assert lc.fetch_page("http://10.0.0.100:3000/") == ""


def test_page_text_drops_scripts_and_nav():
    html = ("<html><head><style>x{}</style><script>var s=1</script></head><body><nav>Menu</nav>"
            "<h1>Forecast</h1><p>Rain &amp; 12&deg;C   tomorrow.</p><footer>(c)</footer></body></html>")
    assert lc.page_text(html) == "Forecast Rain & 12°C tomorrow."


def test_with_sources_includes_page_text():
    out = lc.with_sources("q?", [{"title": "T", "url": "u", "snippet": "s", "page": "full text"},
                                 {"title": "T2", "url": "u2", "snippet": "s2"}])
    assert "Page text: full text" in out and out.count("Page text:") == 1


@pytest.fixture
def media_root(tmp_path, monkeypatch):
    comfy, speech = tmp_path / "comfyui", tmp_path / "speech"
    comfy.mkdir(), speech.mkdir()
    monkeypatch.setattr(lc, "MEDIA_ROOTS", (comfy, speech))
    return tmp_path


def test_media_file_allows_outputs(media_root):
    f = media_root / "comfyui" / "image_1.png"
    f.write_bytes(b"x")
    assert lc.media_file(str(f)) == f.resolve()


@pytest.mark.parametrize("rel", ["comfyui/../secret.png", "elsewhere.png", "comfyui/notes.txt",
                                 "comfyui/missing.png"])
def test_media_file_refuses_traversal_and_types(media_root, rel):
    (media_root / "secret.png").write_bytes(b"x")
    (media_root / "elsewhere.png").write_bytes(b"x")
    (media_root / "comfyui" / "notes.txt").write_text("x")
    with pytest.raises(ValueError):
        lc.media_file(str(media_root / rel))


def test_media_file_refuses_symlink_out(media_root):
    (media_root / "secret.png").write_bytes(b"x")
    link = media_root / "comfyui" / "link.png"
    link.symlink_to(media_root / "secret.png")
    with pytest.raises(ValueError):
        lc.media_file(str(link))


def test_command_pattern():
    assert lc.COMMAND.match("/image a red toolbox").groups() == ("image", "a red toolbox")
    assert lc.COMMAND.match("/video x").group(1) == "video"
    assert lc.COMMAND.match("/speak hi").group(1) == "speak"
    assert not lc.COMMAND.match("/imagine x") and not lc.COMMAND.match("make an /image x")


def test_run_command_image_collects_media(monkeypatch, tmp_path):
    monkeypatch.setattr(lc, "OUTPUTS", tmp_path)
    monkeypatch.setattr(lc, "CHATS", tmp_path / "chats")
    out_png = str(tmp_path / "comfyui" / "image_00001_.png")
    seen = {}

    def fake_run(cmd, timeout=120, **kw):
        seen["cmd"], seen["timeout"] = cmd, timeout
        return {"ok": True, "output": f"queued image abc\n{out_png}\nimage: 30.0 s"}
    monkeypatch.setattr(lc, "_run", fake_run)
    r = lc.chat({"chat_id": "a" * 32, "text": "/image a red toolbox"})
    assert r["ok"] and r["media"] == [{"path": out_png, "kind": "image"}]
    assert seen["cmd"][-2:] == ["image", "a red toolbox"] and seen["timeout"] == lc.JOB_TIMEOUT["image"]
    saved = [json.loads(l) for l in (tmp_path / "chats" / ("a" * 32 + ".jsonl")).read_text().splitlines()]
    assert saved[-1]["media"][0]["kind"] == "image"


def test_run_command_failure_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(lc, "CHATS", tmp_path)
    monkeypatch.setattr(lc, "_run", lambda cmd, timeout=120, **kw: {"ok": False, "output": "boom"})
    r = lc.chat({"chat_id": "b" * 32, "text": "/video x"})
    assert not r["ok"] and "boom" in r["error"]


def test_speak_reply_attaches_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(lc, "CHATS", tmp_path / "chats")
    monkeypatch.setitem(lc.BACKENDS, "heretic", lambda msgs, **kw: {"ok": True, "text": "Hello."})
    monkeypatch.setattr(lc, "speak", lambda text: {"ok": True, "media": {"path": "/x.wav", "kind": "audio"}})
    r = lc.chat({"chat_id": "c" * 32, "text": "hi", "speak": True})
    assert r["media"] == [{"path": "/x.wav", "kind": "audio"}]


def test_speak_failure_keeps_the_text_reply(monkeypatch, tmp_path):
    monkeypatch.setattr(lc, "CHATS", tmp_path / "chats")
    monkeypatch.setitem(lc.BACKENDS, "heretic", lambda msgs, **kw: {"ok": True, "text": "Hello."})
    monkeypatch.setattr(lc, "speak", lambda text: {"ok": False, "error": "TTS unreachable"})
    r = lc.chat({"chat_id": "d" * 32, "text": "hi", "speak": True})
    assert r["ok"] and r["text"] == "Hello." and r["note"] == "TTS unreachable"


def test_saved_sources_drop_page_text(monkeypatch, tmp_path):
    monkeypatch.setattr(lc, "CHATS", tmp_path / "chats")
    seen = {}
    monkeypatch.setitem(lc.BACKENDS, "heretic", lambda msgs, **kw: seen.update(prompt=msgs[-1]["content"]) or {"ok": True, "text": "ok"})
    monkeypatch.setattr(lc, "web_search", lambda q: {"ok": True, "results": [
        {"title": "T", "url": "https://e.com", "snippet": "s", "page": "PAGE BODY"}]})
    r = lc.chat({"chat_id": "e" * 32, "text": "weather?", "web": True})
    assert "PAGE BODY" in seen["prompt"]
    assert r["sources"] == [{"title": "T", "url": "https://e.com", "snippet": "s"}]


def test_think_flag_reaches_heretic_only(monkeypatch, tmp_path):
    monkeypatch.setattr(lc, "CHATS", tmp_path / "chats")
    seen = {}
    monkeypatch.setitem(lc.BACKENDS, "heretic", lambda msgs, **kw: seen.update(kw) or {"ok": True, "text": "ok"})
    lc.chat({"chat_id": "f" * 32, "text": "hi", "think": True})
    assert seen == {"think": True}
    seen.clear()
    lc.chat({"chat_id": "f" * 32, "text": "again"})
    assert seen == {"think": False}


class _Resp:
    def __init__(self, payload, status=200):
        self.payload = json.dumps(payload).encode() if isinstance(payload, (dict, list)) else payload
        self.status = status
        self.code = status

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return self.payload


HERETIC_ANSWER = {"choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
                  "usage": {"total_tokens": 10}}


def test_ask_heretic_503_then_success(monkeypatch):
    posts = []
    health_polls = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/health" in url:
            health_polls.append(url)
            return _Resp({"status": "ok"}, status=200)
        posts.append(url)
        if len(posts) == 1:
            raise urllib.error.HTTPError(url, 503, "Loading model", {}, None)
        return _Resp(HERETIC_ANSWER)

    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
    r = lc.ask_heretic([{"role": "user", "content": "ping"}])
    assert r["ok"] is True
    assert r["text"] == "pong"
    assert len(posts) == 2
    assert len(health_polls) >= 1


def test_ask_heretic_remote_disconnected_then_success(monkeypatch):
    posts = []
    health_polls = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/health" in url:
            health_polls.append(url)
            return _Resp({"status": "ok"}, status=200)
        posts.append(url)
        if len(posts) == 1:
            raise http.client.RemoteDisconnected("Remote end closed connection without response")
        return _Resp(HERETIC_ANSWER)

    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
    r = lc.ask_heretic([{"role": "user", "content": "ping"}])
    assert r["ok"] is True
    assert r["text"] == "pong"
    assert len(posts) == 2
    assert len(health_polls) >= 1


def test_ask_heretic_503_twice_retries_once_only(monkeypatch):
    posts = []
    health_polls = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/health" in url:
            health_polls.append(url)
            return _Resp({"status": "ok"}, status=200)
        posts.append(url)
        raise urllib.error.HTTPError(url, 503, "Loading model", {}, None)

    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
    r = lc.ask_heretic([{"role": "user", "content": "ping"}])
    assert r["ok"] is False
    assert len(posts) == 2
    assert "unreachable" in r["error"]


def test_ask_heretic_health_never_200_fails_without_retry(monkeypatch):
    posts = []
    health_polls = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/health" in url:
            health_polls.append(url)
            raise urllib.error.HTTPError(url, 503, "Loading model", {}, None)
        posts.append(url)
        raise urllib.error.HTTPError(url, 503, "Loading model", {}, None)

    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)

    clock_time = [0.0]
    monkeypatch.setattr(lc, "_clock", lambda: clock_time[0])

    def fake_sleep(s):
        clock_time[0] += s

    monkeypatch.setattr(lc, "_sleep", fake_sleep)

    r = lc.ask_heretic([{"role": "user", "content": "ping"}])
    assert r["ok"] is False
    assert len(posts) == 1
    assert len(health_polls) >= 1
    assert "unreachable" in r["error"]
    assert "waited" in r["error"]


def test_ask_heretic_http_400_fails_without_retry_or_health_poll(monkeypatch):
    posts = []
    health_polls = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/health" in url:
            health_polls.append(url)
            return _Resp({"status": "ok"}, status=200)
        posts.append(url)
        raise urllib.error.HTTPError(url, 400, "Bad Request", {}, None)

    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
    r = lc.ask_heretic([{"role": "user", "content": "ping"}])
    assert r["ok"] is False
    assert len(posts) == 1
    assert len(health_polls) == 0
    assert "unreachable" in r["error"]


def test_ask_heretic_connection_refused_fails_fast(monkeypatch):
    # Refused means Heretic is off: keep the instant "start it" hint, don't wait 240 s.
    posts = []
    health_polls = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/health" in url:
            health_polls.append(url)
            return _Resp({"status": "ok"}, status=200)
        posts.append(url)
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
    r = lc.ask_heretic([{"role": "user", "content": "ping"}])
    assert r["ok"] is False
    assert len(posts) == 1
    assert len(health_polls) == 0
    assert "unreachable" in r["error"]


def test_empty_search_is_an_error_naming_blocked_engines(monkeypatch):
    payload = {"results": [], "unresponsive_engines": [["google", "Suspended: access denied"],
                                                       ["duckduckgo", "CAPTCHA"]]}
    monkeypatch.setattr(lc.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    r = lc.web_search("latest php exploits")
    assert not r["ok"]
    assert "google (Suspended: access denied)" in r["error"] and "duckduckgo (CAPTCHA)" in r["error"]


def test_empty_search_stops_the_answer(monkeypatch, tmp_path):
    monkeypatch.setattr(lc, "CHATS", tmp_path / "chats")
    monkeypatch.setattr(lc, "web_search", lambda q: {"ok": False, "error": "web search found nothing"})
    monkeypatch.setitem(lc.BACKENDS, "heretic", lambda msgs, **kw: pytest.fail("must not answer blind"))
    r = lc.chat({"chat_id": "9" * 32, "text": "latest php exploits", "web": True})
    assert not r["ok"] and "found nothing" in r["error"]


def test_prune_speech_removes_only_old_chat_wavs(tmp_path):
    import os
    old, new, sample = tmp_path / "chat-old.wav", tmp_path / "chat-new.wav", tmp_path / "default-voice.wav"
    for f in (old, new, sample):
        f.write_bytes(b"x")
    long_ago = 1_000_000
    os.utime(old, (long_ago, long_ago))
    os.utime(sample, (long_ago, long_ago))
    assert lc.prune_speech(tmp_path, days=7, now=long_ago + 8 * 86400) == 1
    assert not old.exists() and new.exists() and sample.exists()

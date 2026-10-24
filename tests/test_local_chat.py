import importlib.util
import json
import socket
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

"""Tests for scripts/live_preview (publisher, CLI, MCP server, vendored viewer).

Sessions go to a tmp LIVE_PREVIEW_HOME; the watch test serves on 127.0.0.1 port 0.
"""
import asyncio
import json
import multiprocessing as mp
import os
import struct
import sys
import urllib.error
import urllib.request
import zlib
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))

from live_preview import bundle as pb  # noqa: E402
from live_preview import cli  # noqa: E402
from live_preview import publish as lp  # noqa: E402
from live_preview import server  # noqa: E402


def _png(path: Path, rgb=(200, 60, 60), w=8, h=8) -> str:
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return str(path)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_PREVIEW_HOME", str(tmp_path / "home"))
    return tmp_path


# --- publishing ---------------------------------------------------------------

def test_publish_builds_a_session_the_viewer_can_read(home):
    img = _png(home / "a.png")
    lp.publish("proj", "s1", [img], "first", note="why")
    r = lp.publish("proj", "s1", [img, _png(home / "b.png", (1, 2, 3))], "second")
    assert r["step_count"] == 2 and r["step"] == "step-0002"

    sdir = lp.session_path("proj", "s1")
    manifest = json.loads((sdir / "current" / "manifest.json").read_text())
    assert manifest["bundle_id"] == r["bundle_id"]
    assert [a["role"] for a in manifest["artifacts"]] == ["hero", "view"]
    assert lp.status("proj", "s1")["latest_label"] == "second"
    # The vendored reader accepts what we wrote.
    inspected = pb.load_live_trajectory(sdir)
    assert inspected["step_count"] == 2


def _publish_many(home_dir, worker, n, img):
    os.environ["LIVE_PREVIEW_HOME"] = home_dir
    for i in range(n):
        lp.publish("proj", "shared", [img], f"agent{worker}-{i}")


def test_concurrent_publishers_never_drop_steps(home):
    img = _png(home / "a.png")
    ctx = mp.get_context("fork")
    procs = [ctx.Process(target=_publish_many, args=(os.environ["LIVE_PREVIEW_HOME"], w, 3, img))
             for w in range(6)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    st = json.loads((lp.session_path("proj", "shared") / "session.json").read_text())
    assert st["trajectory_step_count"] == 18
    assert len(st["history"]) == 18
    labels = {h["stage_label"] for h in st["history"]}
    assert len(labels) == 18


def test_prune_keeps_newest_bundles_and_all_steps(home):
    img = _png(home / "a.png")
    for i in range(4):
        r = lp.publish("proj", "p", [img], f"s{i}", keep=2)
    sdir = lp.session_path("proj", "p")
    bundles = [d for d in (sdir / "bundles").glob("*/*/*") if (d / "manifest.json").is_file()]
    assert len(bundles) == 2
    assert r["step_count"] == 4
    # The survivors are the two newest steps, even though all four land in the same second.
    kept = {json.loads((d / "summary.json").read_text())["headline"] for d in bundles}
    assert kept == {"s2", "s3"}
    assert json.loads((sdir / "current" / "summary.json").read_text())["headline"] == "s3"


# --- interrupted writes -------------------------------------------------------

@pytest.mark.parametrize("writer", [
    lambda p, d: lp.write_json_atomic(p, d),
    lambda p, d: pb.write_json(str(p), d),
])
def test_interrupted_write_leaves_old_file_intact(tmp_path, monkeypatch, writer):
    target = tmp_path / "session.json"
    writer(target, {"v": 1})

    def boom(*a, **k):
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        writer(target, {"v": 2})
    assert json.loads(target.read_text()) == {"v": 1}


# --- input validation ---------------------------------------------------------

def test_non_image_is_refused(home):
    secret = home / "id_ed25519"
    secret.write_text("PRIVATE KEY")
    with pytest.raises(ValueError):
        lp.publish("proj", "s", [str(secret)], "x")


def test_renamed_non_image_is_refused(home):
    fake = home / "key.png"
    fake.write_text("-----BEGIN OPENSSH PRIVATE KEY-----")
    with pytest.raises(ValueError, match="not a .png image"):
        lp.publish("proj", "s", [str(fake)], "x")


def test_symlinked_image_is_refused(home):
    real = Path(_png(home / "real.png"))
    link = home / "link.png"
    link.symlink_to(real)
    with pytest.raises(ValueError, match="symlink"):
        lp.publish("proj", "s", [str(link)], "x")


@pytest.mark.parametrize("project,session", [("..", "s"), ("a/b", "s"), ("p", "../../x"), ("", "s"), ("p", ".hidden")])
def test_bad_names_are_refused(home, project, session):
    with pytest.raises(ValueError):
        lp.publish(project, session, [_png(home / "a.png")], "x")
    assert not (home / "x").exists()


def test_mcp_tools_return_errors_not_raise(home):
    assert "error" in server._guard(lp.publish, "proj", "s", [str(home / "missing.png")], "x")
    assert "error" in server._guard(lp.status, "proj", "nope")
    assert server.stop("proj", "never") == {"error": "not_watching"}


def test_mcp_server_registers_four_tools():
    names = {t.name for t in asyncio.run(server.build_server().list_tools())}
    assert names == {"preview_publish", "preview_watch", "preview_stop", "preview_status"}


# --- watching -----------------------------------------------------------------

def test_watch_serves_page_state_and_current_image_on_localhost(home):
    lp.publish("proj", "w", [_png(home / "hero.png")], "only")
    srv, url = cli.start_watch("proj", "w")
    try:
        assert url.startswith("http://127.0.0.1:")
        base = url.rsplit("/", 1)[0]
        for rel in ["index.html", "session.json", "trajectory.json", "current/manifest.json",
                    "current/artifacts/00-hero.png"]:
            with urllib.request.urlopen(f"{base}/{rel}", timeout=5) as resp:
                assert resp.status == 200, rel
    finally:
        srv.shutdown()


@pytest.mark.parametrize("keep", [0, -1])
def test_nonpositive_keep_is_refused(home, keep):
    with pytest.raises(ValueError, match="keep"):
        lp.publish("proj", "k", [_png(home / "a.png")], "x", keep=keep)


def test_same_stem_images_get_distinct_ids(home):
    png = _png(home / "a.png")
    gif = home / "a.gif"
    gif.write_bytes(b"GIF89a" + b"\x00" * 20)
    lp.publish("proj", "ids", [png, str(gif)], "x")
    manifest = json.loads((lp.session_path("proj", "ids") / "current" / "manifest.json").read_text())
    ids = [a["artifact_id"] for a in manifest["artifacts"]]
    assert len(set(ids)) == 2


def test_watch_is_idempotent_and_stop_releases_the_port(home):
    lp.publish("proj", "ws", [_png(home / "a.png")], "x")
    first = server.watch("proj", "ws")
    assert server.watch("proj", "ws") == {"url": first["url"], "already_running": True}
    port = int(first["url"].split(":")[2].split("/")[0])
    assert server.stop("proj", "ws") == {"stopped": first["url"]}
    again = server.watch("proj", "ws", port=port)  # would fail "address in use" without server_close
    try:
        assert again["url"] == first["url"]
    finally:
        server.stop("proj", "ws")


# --- security review findings (2026-10-17) -----------------------------------

def test_hostile_filename_never_reaches_the_page(home):
    evil = home / 'x" onerror=alert(1) a=".png'
    _png(evil)
    lp.publish("proj", "xss", [str(evil)], "x")
    manifest_text = (lp.session_path("proj", "xss") / "current" / "manifest.json").read_text()
    assert "onerror" not in manifest_text
    assert json.loads(manifest_text)["artifacts"][0]["path"] == "artifacts/00-hero.png"


def test_file_swapped_after_validation_is_not_what_gets_copied(home):
    img = home / "a.png"
    _png(img)
    secret = home / "secret.txt"
    secret.write_text("PRIVATE KEY")
    fd, suffix = lp.open_image(str(img))
    try:
        img.unlink()
        img.symlink_to(secret)  # the swap an attacker would race in
        dest = home / "copy.png"
        lp._copy_fd(fd, dest)
    finally:
        os.close(fd)
    assert dest.read_bytes().startswith(b"\x89PNG")
    assert b"PRIVATE" not in dest.read_bytes()


def test_device_is_refused(home):
    devnull = home / "zero.png"
    devnull.symlink_to("/dev/zero")
    with pytest.raises(ValueError):
        lp.publish("proj", "s", [str(devnull)], "x")


def test_caps_on_images_and_text(home):
    img = _png(home / "a.png")
    with pytest.raises(ValueError, match="at most"):
        lp.publish("proj", "s", [img] * (lp.MAX_IMAGES_PER_STEP + 1), "x")
    with pytest.raises(ValueError, match="note longer"):
        lp.publish("proj", "s", [img], "x", note="n" * (lp.MAX_TEXT_CHARS + 1))


def test_sessions_root_is_private(home):
    lp.publish("proj", "s", [_png(home / "a.png")], "x")
    assert (lp.sessions_root().stat().st_mode & 0o077) == 0


@pytest.mark.parametrize("port", [-1, 80, 65536, "8080"])
def test_bad_ports_are_refused(home, port):
    lp.publish("proj", "pt", [_png(home / "a.png")], "x")
    assert "error" in server._guard(server.watch, "proj", "pt", port)


def test_foreign_host_header_and_directory_listing_are_refused(home):
    lp.publish("proj", "h", [_png(home / "a.png")], "x")
    srv, url = cli.start_watch("proj", "h")
    base = url.rsplit("/", 1)[0]
    try:
        req = urllib.request.Request(f"{base}/session.json", headers={"Host": "evil.example:80"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        assert e.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"{base}/bundles/", timeout=5)
        assert e.value.code == 404
    finally:
        srv.shutdown()
        srv.server_close()


def test_cli_publish_and_status_print_json(home, capsys):
    img = _png(home / "a.png")
    assert cli.main(["publish", "--project", "proj", "--session", "c", "--label", "hi", img]) == 0
    assert json.loads(capsys.readouterr().out)["step_count"] == 1
    assert cli.main(["status", "--project", "proj", "--session", "c"]) == 0
    assert json.loads(capsys.readouterr().out)["latest_label"] == "hi"
    assert cli.main(["publish", "--project", "proj", "--session", "c", "--label", "x", "/nope.png"]) == 1
    assert "error" in json.loads(capsys.readouterr().out)

"""Tests for scripts/scout/message.py — Telegram text and keyboards."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scout import message  # noqa: E402
from scout.gh import Facts  # noqa: E402

PICK = {"pick": "a/b", "gap": "no wake word", "take": "Small and local.", "risk": "Young.",
        "fit": True, "scores": {"tokens": 3, "accuracy": 4, "creativity": 2, "offline": 5}}


def _facts(**over):
    d = dict(id=7, full_name="a/b", html_url="https://github.com/a/b", description="desc",
             stars=49478, license="MIT", pushed_at="2026-10-15T16:16:00Z", archived=False,
             fork=False, topics=[])
    d.update(over)
    return Facts(**d)


def test_render_escapes_html():
    out = message.render_find("voice", "thin", _facts(description="<script>&"), PICK, "discovered")
    assert "&lt;script&gt;&amp;" in out
    assert "<script>" not in out


def test_render_strips_urls_from_description():
    out = message.render_find("voice", "thin", _facts(description="Docs at https://evil.example/x now"),
                              PICK, "discovered")
    assert "evil.example" not in out and "Docs at" in out


def test_render_watchlist_label():
    out = message.render_find("", "", _facts(), PICK, "watchlist")
    assert "new release" in out


def test_send_payload_disables_link_previews():
    p = message.send_payload("555", "hi", message.keyboard_find(1))
    assert p["link_preview_options"] == {"is_disabled": True}
    assert p["parse_mode"] == "HTML" and p["chat_id"] == "555"
    assert p["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "scout:yes:1"


def test_render_facts_line_from_facts_only():
    out = message.render_find("voice", "thin", _facts(), PICK, "discovered")
    assert "★49478" in out and "MIT" in out and "2026-10-15" in out


def test_render_caps_length_keeps_facts_and_scores():
    long = {**PICK, "take": "This is a sentence. " * 300}
    out = message.render_find("voice", "thin", _facts(), long, "discovered")
    assert len(out) <= message.MAX_LEN
    assert "★49478" in out and "offline 5/5" in out


def test_render_find_inbox_label():
    out = message.render_find("", "", _facts(), PICK, "inbox")
    assert "from your inbox" in out


def test_render_eval_has_verdict_and_sketch():
    ev = {"verdict": "trial", "summary": "Looks useful.", "trial_sketch": "Wire it up.",
          "risks": ["<b>x</b>"]}
    out = message.render_eval(_facts(), ev)
    assert "trial" in out.lower() and "Wire it up." in out and "&lt;b&gt;" in out


def test_keyboard_callback_data_under_64_bytes():
    for kb in (message.keyboard_find(2**40), message.keyboard_eval(2**40)):
        rows = json.loads(kb)
        for b in rows[0]:
            assert b["callback_data"].startswith("scout:")
            assert len(b["callback_data"].encode()) <= 64


def test_keyboard_find_values():
    datas = [b["callback_data"] for b in json.loads(message.keyboard_find(9))[0]]
    assert datas == ["scout:yes:9", "scout:maybe:9", "scout:no:9"]
    datas = [b["callback_data"] for b in json.loads(message.keyboard_eval(9))[0]]
    assert datas == ["scout:e-yes:9", "scout:e-maybe:9", "scout:e-no:9"]


def test_trim_never_leaves_partial_entity():
    import re
    for n in range(1, 12):
        out = message._trim("&amp;" * 40, n)
        assert not re.search(r"&[a-z#0-9]*…$", out), out

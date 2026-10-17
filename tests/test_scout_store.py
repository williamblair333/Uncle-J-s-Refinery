"""Tests for scripts/scout/store.py — the scout's state files."""
import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scout import store  # noqa: E402

NOW = datetime.datetime(2026, 10, 17, 4, 15, tzinfo=datetime.timezone.utc)


def test_read_inbox_parses_urls_and_slugs(tmp_path):
    p = tmp_path / "inbox.md"
    p.write_text(
        "# Inbox\n- https://github.com/MadsLorentzen/ai-job-search.git\n- foo/bar\n<!-- x -->\n\n"
    )
    assert store.read_inbox(p) == ["MadsLorentzen/ai-job-search", "foo/bar"]


def test_read_inbox_missing_file_is_empty(tmp_path):
    assert store.read_inbox(tmp_path / "nope.md") == []


def test_record_answer_and_is_known():
    d = {"finds": {}}
    store.record_answer(d, 42, "a/b", 1, "no", "too heavy", NOW)
    assert store.is_known(d, 42)
    assert not store.is_known(d, 43)
    assert d["finds"]["42"]["answer"] == "no"
    assert d["finds"]["42"]["reason"] == "too heavy"
    assert d["finds"]["42"]["full_name"] == "a/b"


def test_map_reviewed_false_when_missing_or_unset(tmp_path):
    m = tmp_path / "map.md"
    assert store.map_reviewed(m) is False
    m.write_text("---\nreviewed: false\n---\n# Map\n")
    assert store.map_reviewed(m) is False
    m.write_text("---\nreviewed: true\n---\n# Map\n")
    assert store.map_reviewed(m) is True


def test_load_json_corrupt_returns_default(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{not json")
    assert store.load_json(p, {"q": []}) == {"q": []}


def test_save_json_roundtrip_leaves_no_tmp(tmp_path):
    p = tmp_path / "sub" / "x.json"
    store.save_json(p, {"a": 1})
    assert store.load_json(p, None) == {"a": 1}
    assert [f.name for f in p.parent.iterdir()] == ["x.json"]


def test_paths_layout(tmp_path):
    p = store.Paths(tmp_path)
    assert p.answers == tmp_path / "scout" / "answers.json"
    assert p.pending == tmp_path / "state" / "scout-pending.json"
    assert p.callbacks == tmp_path / "state" / "scout-callbacks.jsonl"

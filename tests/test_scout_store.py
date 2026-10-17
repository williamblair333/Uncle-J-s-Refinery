"""Tests for scripts/scout/store.py — the scout's state files."""
import datetime
import json
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


def _tap(paths, msg_id, data):
    paths.callbacks.parent.mkdir(parents=True, exist_ok=True)
    with open(paths.callbacks, "a") as f:
        f.write(json.dumps({"message_id": msg_id, "data": data, "ts": 0}) + "\n")


def _pending(hours_ago=1, msg_id=10, repo_id=42, rung=1):
    sent = NOW - datetime.timedelta(hours=hours_ago)
    return {"message_id": msg_id, "repo_id": repo_id, "full_name": "a/b", "rung": rung,
            "sent_at": sent.strftime("%Y-%m-%dT%H:%M:%SZ")}


def test_apply_first_answer_wins(tmp_path):
    paths = store.Paths(tmp_path)
    _tap(paths, 10, "scout:yes:42")
    _tap(paths, 10, "scout:no:42")
    ans, pend = store.apply_callbacks(paths, {"finds": {}}, _pending(), NOW)
    assert ans["finds"]["42"]["answer"] == "yes"
    assert pend is None
    assert not paths.callbacks.exists()


def test_apply_reason_only_after_no(tmp_path):
    paths = store.Paths(tmp_path)
    _tap(paths, 10, "scout:r-heavy:42")
    ans, pend = store.apply_callbacks(paths, {"finds": {}}, _pending(), NOW)
    assert "42" not in ans["finds"]
    assert pend is not None
    _tap(paths, 10, "scout:no:42")
    _tap(paths, 10, "scout:r-heavy:42")
    ans, pend = store.apply_callbacks(paths, ans, pend, NOW)
    assert ans["finds"]["42"]["answer"] == "no"
    assert ans["finds"]["42"]["reason"] == "too heavy"


def test_apply_expiry_48h_to_maybe(tmp_path):
    paths = store.Paths(tmp_path)
    ans, pend = store.apply_callbacks(paths, {"finds": {}}, _pending(hours_ago=49), NOW)
    assert ans["finds"]["42"]["answer"] == "maybe"
    assert ans["finds"]["42"]["expired"] is True
    assert pend is None


def test_apply_not_expired_at_47h(tmp_path):
    paths = store.Paths(tmp_path)
    ans, pend = store.apply_callbacks(paths, {"finds": {}}, _pending(hours_ago=47), NOW)
    assert "42" not in ans["finds"] and pend is not None


def test_apply_late_tap_upgrades_expired_maybe(tmp_path):
    paths = store.Paths(tmp_path)
    ans, _ = store.apply_callbacks(paths, {"finds": {}}, _pending(hours_ago=49), NOW)
    _tap(paths, 10, "scout:yes:42")
    ans, _ = store.apply_callbacks(paths, ans, None, NOW)
    assert ans["finds"]["42"]["answer"] == "yes"
    assert "expired" not in ans["finds"]["42"]


def test_apply_eval_answers_set_rung2(tmp_path):
    paths = store.Paths(tmp_path)
    ans = {"finds": {"42": {"full_name": "a/b", "rung": 1, "answer": "yes"}}}
    _tap(paths, 11, "scout:e-yes:42")
    ans, pend = store.apply_callbacks(paths, ans, _pending(msg_id=11, rung=2), NOW)
    assert ans["finds"]["42"]["rung"] == 2 and ans["finds"]["42"]["answer"] == "yes"
    assert pend is None


def test_apply_tap_during_read_is_not_lost(tmp_path):
    # The gateway may append while the scout reads: the scout renames the file aside
    # first, so a line appended after the rename lands in a fresh file for next time.
    paths = store.Paths(tmp_path)
    _tap(paths, 10, "scout:yes:42")
    real_replace = store.os.replace
    def replace_then_tap(a, b):
        real_replace(a, b)
        if str(a) == str(paths.callbacks):
            _tap(paths, 99, "scout:no:7")
    store.os.replace = replace_then_tap
    try:
        store.apply_callbacks(paths, {"finds": {}}, None, NOW)
    finally:
        store.os.replace = real_replace
    assert "scout:no:7" in paths.callbacks.read_text()


def test_paths_layout(tmp_path):
    p = store.Paths(tmp_path)
    assert p.answers == tmp_path / "scout" / "answers.json"
    assert p.pending == tmp_path / "state" / "scout-pending.json"
    assert p.callbacks == tmp_path / "state" / "scout-callbacks.jsonl"

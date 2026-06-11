import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import citation_audit as ca


def _line(obj):
    import json
    return json.dumps(obj)


def test_extract_urls_from_assistant_text():
    rec = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "see https://github.com/foo/bar and http://x.io/y page"}]}}
    urls = ca.extract_urls_from_record(rec)
    assert "https://github.com/foo/bar" in urls
    assert "http://x.io/y" in urls


def test_collect_fetched_urls_from_webfetch_and_gh():
    recs = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "WebFetch", "input": {"url": "https://github.com/foo/bar"}}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash",
             "input": {"command": "gh api repos/foo/bar/issues/3"}}]}},
    ]
    fetched = ca.collect_fetched_evidence(recs)
    assert "https://github.com/foo/bar" in fetched["urls"]
    assert any("repos/foo/bar/issues/3" in c for c in fetched["gh_cmds"])


def test_classify_url_verified_by_webfetch():
    fetched = {"urls": {"https://github.com/foo/bar"}, "gh_cmds": []}
    assert ca.classify_url("https://github.com/foo/bar", fetched) == "verified"


def test_classify_url_verified_by_gh_path_match():
    fetched = {"urls": set(), "gh_cmds": ["gh api repos/foo/bar/issues/3"]}
    assert ca.classify_url("https://github.com/foo/bar/issues/3", fetched) == "verified"


def test_classify_url_unverified():
    fetched = {"urls": set(), "gh_cmds": []}
    assert ca.classify_url("https://example.com/made-up", fetched) == "unverified"


def test_audit_transcript_builds_records(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join([
        _line({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "WebFetch", "input": {"url": "https://real.io/a"}}]}}),
        _line({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "cite https://real.io/a and https://fake.io/b"}]}}),
    ]))
    records = ca.audit_transcript(f)
    by_url = {r["url"]: r["status"] for r in records}
    assert by_url["https://real.io/a"] == "verified"
    assert by_url["https://fake.io/b"] == "unverified"
    assert all("session" in r and "ts" in r for r in records)

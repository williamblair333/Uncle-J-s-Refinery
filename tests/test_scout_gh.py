"""Tests for scripts/scout/gh.py — GitHub facts come only from `gh api`."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scout import gh  # noqa: E402


def _repo(**over):
    d = {
        "id": 1076543210, "full_name": "MadsLorentzen/ai-job-search",
        "html_url": "https://github.com/MadsLorentzen/ai-job-search",
        "description": "AI job application framework", "stargazers_count": 49478,
        "license": {"spdx_id": "MIT"}, "pushed_at": "2026-10-15T16:16:00Z",
        "archived": False, "fork": False, "topics": ["claude-code"],
    }
    d.update(over)
    return d


def _runner(rc, payload):
    calls = []

    def run(args):
        calls.append(args)
        return rc, payload if isinstance(payload, str) else json.dumps(payload)

    run.calls = calls
    return run


def test_repo_facts_maps_fields():
    f = gh.repo_facts("MadsLorentzen/ai-job-search", run=_runner(0, _repo()))
    assert f.stars == 49478
    assert f.license == "MIT"
    assert isinstance(f.id, int) and f.id == 1076543210
    assert f.pushed_at == "2026-10-15T16:16:00Z"


def test_repo_facts_rename_uses_response_name():
    f = gh.repo_facts("old/name", run=_runner(0, _repo(full_name="new/name")))
    assert f.full_name == "new/name"


def test_repo_facts_gh_failure_returns_none():
    assert gh.repo_facts("a/b", run=_runner(1, "")) is None
    assert gh.repo_facts("a/b", run=_runner(0, "not json")) is None


def test_repo_facts_no_license_is_none():
    f = gh.repo_facts("a/b", run=_runner(0, _repo(license=None)))
    assert f.license is None


def test_search_drops_archived_and_forks():
    items = [_repo(id=1), _repo(id=2, archived=True), _repo(id=3, fork=True)]
    run = _runner(0, {"items": items})
    got = gh.search("wake word", limit=10, run=run)
    assert [f.id for f in got] == [1]
    assert "search/repositories" in run.calls[0]


def test_real_search_is_paced_under_rate_limit(monkeypatch):
    # GitHub allows 30 searches a minute; seeding runs ~60 back to back.
    sleeps, clock = [], [100.0]
    monkeypatch.setattr(gh, "_gh", _runner(0, {"items": []}))
    monkeypatch.setattr(gh, "_clock", lambda: clock[0])
    monkeypatch.setattr(gh, "_sleep", lambda s: (sleeps.append(s), clock.__setitem__(0, clock[0] + s)))
    monkeypatch.setattr(gh, "_last_search", 0.0)
    gh.search("a")
    gh.search("b")
    assert sleeps and abs(sleeps[0] - gh.SEARCH_INTERVAL) < 0.01


def test_search_checked_distinguishes_failure_from_empty():
    assert gh.search_checked("x", run=_runner(0, {"items": []})) == []
    assert gh.search_checked("x", run=_runner(1, "")) is None


def test_latest_release_date_and_none():
    assert gh.latest_release("a/b", run=_runner(0, {"published_at": "2026-10-10T00:00:00Z"})) \
        == "2026-10-10T00:00:00Z"
    assert gh.latest_release("a/b", run=_runner(1, "")) is None


def test_search_failure_is_empty():
    assert gh.search("x", run=_runner(1, "")) == []


def test_readme_caps_length_and_failure_is_empty():
    assert len(gh.readme("a/b", run=_runner(0, "x" * 50000))) == 20000
    assert gh.readme("a/b", run=_runner(1, "boom")) == ""

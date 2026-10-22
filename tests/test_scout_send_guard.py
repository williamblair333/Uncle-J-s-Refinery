"""Repo scout: idempotent Telegram send, one message per calendar day, run lock,
`run done` marker, library-eval routing, and the gh facts log (spec §10)."""
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scout import run, store  # noqa: E402
from scout.gh import Facts  # noqa: E402
from test_scout_run import NOW, F, Fake, setup  # noqa: E402


def test_timeout_after_send_is_not_retried(tmp_path):
    paths = setup(tmp_path, inbox=["o/r1"])
    fake = Fake(repos=[F(1)])
    calls = []
    fake.send = lambda text, kb: calls.append(text) or run.SEND_UNCERTAIN
    run.run_once(paths, fake.deps(), "INV")
    pending = store.load_json(paths.pending, None)
    assert pending["uncertain"] is True and pending["repo_id"] == 1
    assert store.load_json(paths.queue, []) == []
    # next night: still pending, nothing resent
    later = run.Deps(**{**fake.deps().__dict__, "now": NOW + datetime.timedelta(days=1)})
    run.run_once(paths, later, "INV")
    assert len(calls) == 1


def test_uncertain_pending_is_cleared_by_a_tap_on_that_find(tmp_path):
    paths = setup(tmp_path, inbox=["o/r1"])
    fake = Fake(repos=[F(1)])
    fake.send = lambda text, kb: run.SEND_UNCERTAIN
    run.run_once(paths, fake.deps(), "INV")
    paths.callbacks.write_text(json.dumps({"message_id": 4242, "data": "scout:yes:1"}) + "\n")
    answers, pending = store.apply_callbacks(paths, store.load_answers(paths.answers),
                                             store.load_json(paths.pending, None), NOW)
    assert pending is None
    assert answers["finds"]["1"]["answer"] == "yes"


def test_interrupted_send_is_not_resent(tmp_path):
    """The run died after the Telegram call, before recording it."""
    paths = setup(tmp_path, inbox=["o/r1"])
    fake = Fake(repos=[F(1)])
    store.save_json(paths.queue, [{"repo_id": 1, "full_name": "o/r1", "rung": 1,
                                   "source": "inbox", "judgment": {}, "found_at": "x"}])
    store.save_json(paths.sent, {"date": "2026-10-16", "at": "2026-10-16T04:15:00Z",
                                 "repo_id": 1, "full_name": "o/r1", "rung": 1,
                                 "state": "sending"})
    run.run_once(paths, fake.deps(), "INV")
    assert fake.sent == []
    assert store.load_json(paths.pending, None)["uncertain"] is True
    assert store.load_json(paths.sent, None)["state"] == "uncertain"
    assert all(q["repo_id"] != 1 for q in store.load_json(paths.queue, []))


def test_definite_failure_clears_marker_and_keeps_queued(tmp_path):
    paths = setup(tmp_path, inbox=["o/r1"])
    fake = Fake(repos=[F(1)])
    fake.send = lambda text, kb: None
    run.run_once(paths, fake.deps(), "INV")
    assert not paths.sent.exists()
    assert [q["repo_id"] for q in store.load_json(paths.queue, [])] == [1]


def test_one_message_per_calendar_day(tmp_path):
    paths = setup(tmp_path, inbox=["o/r1", "o/r2"])
    fake = Fake(repos=[F(1), F(2)])
    run.run_once(paths, fake.deps(), "INV")
    assert len(fake.sent) == 1
    # Bill answers straight away; a second run the same day still sends nothing.
    paths.callbacks.write_text(json.dumps({"message_id": 1001, "data": "scout:no:1"}) + "\n")
    run.run_once(paths, fake.deps(), "INV")
    assert len(fake.sent) == 1
    assert "already sent today" in paths.log.read_text()
    tomorrow = run.Deps(**{**fake.deps().__dict__, "now": NOW + datetime.timedelta(days=1)})
    run.run_once(paths, tomorrow, "INV")
    assert len(fake.sent) == 2


def test_dry_run_ignores_the_daily_guard_and_writes_no_marker(tmp_path):
    paths = setup(tmp_path, inbox=["o/r1"])
    store.save_json(paths.sent, {"date": run._today(NOW), "state": "sent", "repo_id": 9,
                                 "full_name": "o/r9", "rung": 1, "at": "x"})
    before = paths.sent.read_bytes()
    out = []
    run.run_once(paths, Fake(repos=[F(1)]).deps(), "INV", dry_run=True, out=out.append)
    assert any("from your inbox" in o for o in out)
    assert paths.sent.read_bytes() == before


def test_sent_message_logs_the_gh_facts_it_used(tmp_path):
    paths = setup(tmp_path, inbox=["o/r1"])
    run.run_once(paths, Fake(repos=[F(1, stars=321)]).deps(), "INV")
    line = next(ln for ln in paths.log.read_text().splitlines() if "gh facts used" in ln)
    logged = json.loads(line.split("gh facts used: ", 1)[1])
    assert logged == {"id": 1, "full_name": "o/r1", "html_url": "https://github.com/o/r1",
                      "stars": 321, "license": "MIT", "pushed_at": "2026-10-01T00:00:00Z"}


def _facts(desc, topics=()):
    return Facts(1, "o/r", "u", desc, 1, None, "", False, False, list(topics))


def test_library_finds_get_the_library_eval_skill():
    assert run.pick_eval_skill(_facts("Fast embedded vector database")) == run.LIBRARY_EVAL_SKILL
    assert run.pick_eval_skill(_facts("x", ["cache", "sdk"])) == run.LIBRARY_EVAL_SKILL
    assert run.pick_eval_skill(_facts("Autonomous coding agent framework")) == run.EVAL_SKILL
    assert run.pick_eval_skill(_facts("agent memory library")) == run.EVAL_SKILL  # tie
    assert run.LIBRARY_EVAL_SKILL.exists() and run.EVAL_SKILL.exists()


def test_evaluate_uses_the_library_method_for_a_library(tmp_path):
    paths = setup(tmp_path)
    store.save_answers(paths.answers, {"finds": {"3": {"full_name": "o/r3", "rung": 1,
                                                       "answer": "yes"}}})
    lib = Facts(3, "o/r3", "https://github.com/o/r3", "A key-value storage engine", 1,
                "MIT", "2026-10-01T00:00:00Z", False, False, ["database"])
    fake = Fake(repos=[lib])
    run.run_once(paths, fake.deps(), "INV")
    prompt = next(p for p in fake.prompts if "evaluation method" in p)
    assert run.LIBRARY_EVAL_SKILL.read_text()[:200] in prompt
    assert "using library-backend-adoption-eval" in paths.log.read_text()


def test_run_lock_refuses_a_second_run(tmp_path):
    paths = store.Paths(tmp_path)
    assert run.acquire_lock(paths) is True
    held = run._lock_handle
    try:
        run._lock_handle = None
        assert run.acquire_lock(store.Paths(tmp_path)) is False
    finally:
        held.close()
    assert run.acquire_lock(paths) is True
    run._lock_handle.close()


def test_main_writes_run_done_and_skips_when_locked(tmp_path, monkeypatch):
    fake = Fake()
    monkeypatch.setattr(run, "real_deps", lambda root: fake.deps())
    monkeypatch.setattr(run.judge, "inventory", lambda root: "INV")
    setup(tmp_path)
    assert run.main(["run", "--root", str(tmp_path)]) == 0
    assert (tmp_path / "state" / "scout.log").read_text().splitlines()[-1].endswith("] run done")
    run._lock_handle.close()
    run._lock_handle = None
    assert run.main(["run", "--dry-run", "--root", str(tmp_path)]) == 0
    assert (tmp_path / "state" / "scout.log").read_text().splitlines()[-1].endswith(
        "run done (dry run)")
    held = run._lock_handle  # still held by this process: a second open must fail
    run._lock_handle = None
    try:
        assert run.main(["run", "--root", str(tmp_path)]) == 1
        assert "skipped" in (tmp_path / "state" / "scout.log").read_text().splitlines()[-1]
    finally:
        held.close()
        run._lock_handle = None

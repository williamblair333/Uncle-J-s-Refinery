"""scripts/lib/tg_history.py — Telegram chat continuity. No network, no model."""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))
import tg_history as h  # noqa: E402

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def test_record_then_context_round_trip(tmp_path):
    log = tmp_path / "h.jsonl"
    h.record("what's the build status?", "Green.", path=log, now=NOW - dt.timedelta(minutes=5))
    ctx = h.recent_context(log, now=NOW)
    assert "You: what's the build status?" in ctx and "Bot: Green." in ctx
    wrapped = h.with_context("and the tests?", log, now=NOW)
    assert wrapped.endswith("Current message:\nand the tests?")
    assert "<earlier>" in wrapped


def test_no_history_leaves_message_unchanged(tmp_path):
    assert h.with_context("hi", tmp_path / "none.jsonl", now=NOW) == "hi"


def test_old_turns_are_not_injected(tmp_path):
    log = tmp_path / "h.jsonl"
    h.record("yesterday", "ok", path=log, now=NOW - dt.timedelta(hours=30))
    assert h.recent_context(log, now=NOW) == ""


def test_gateway_error_notices_are_not_recorded(tmp_path):
    log = tmp_path / "h.jsonl"
    h.record("q", "⚠️ Claude timed out after 120 seconds.", path=log, now=NOW)
    h.record("q", "", path=log, now=NOW)
    assert not log.exists() or log.read_text() == ""


def test_context_is_redacted_and_bounded(tmp_path):
    log = tmp_path / "h.jsonl"
    h.record("see /opt/proj/secret/file.py at a3ac6798fb", "host 10.0.0.100 via mcp__jcodemunch__x",
             path=log, now=NOW)
    ctx = h.recent_context(log, now=NOW)
    for leak in ("/opt/proj", "a3ac6798fb", "10.0.0.100", "mcp__jcodemunch"):
        assert leak not in ctx
    assert "1234567" in h.redact("call 1234567")  # plain numbers aren't hashes
    for i in range(20):
        h.record("x" * 500, "y" * 500, path=log, now=NOW)
    assert len(h.recent_context(log, now=NOW, max_chars=3000)) <= 3000 + 200


def test_log_is_trimmed(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "MAX_LINES", 5)
    log = tmp_path / "h.jsonl"
    for i in range(9):
        h.record(f"q{i}", "a", path=log, now=NOW)
    turns = h.load(log)
    assert [t["user"] for t in turns] == ["q4", "q5", "q6", "q7", "q8"]


def test_record_never_raises(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("")
    h.record("q", "a", path=blocker / "sub" / "h.jsonl", now=NOW)  # parent is a file


class FakeRail:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def chat(self, job, prompt, **kw):
        self.prompts.append(prompt)
        return dict(self.reply)


def test_summarize_writes_finished_days_only(tmp_path):
    log, corpus = tmp_path / "h.jsonl", tmp_path / "corpus"
    h.record("old q /opt/x/y", "old a", path=log, now=dt.datetime(2026, 10, 21, 9, tzinfo=UTC))
    h.record("today q", "today a", path=log, now=NOW)
    rail = FakeRail({"text": "- asked about x", "model": "heretic"})
    assert h.summarize(log=log, corpus=corpus, rail=rail, today=NOW.date()) == 0
    files = sorted(p.name for p in corpus.iterdir())
    assert files == ["telegram-2026-10-21.md"]
    assert "/opt/x" not in rail.prompts[0]  # redacted before it reaches the model
    # Idempotent: an existing summary isn't redone.
    assert h.summarize(log=log, corpus=corpus, rail=rail, today=NOW.date()) == 0
    assert len(rail.prompts) == 1


def test_summarize_failure_writes_nothing_and_reports(tmp_path):
    log, corpus = tmp_path / "h.jsonl", tmp_path / "corpus"
    h.record("q", "a", path=log, now=dt.datetime(2026, 10, 21, 9, tzinfo=UTC))
    assert h.summarize(log=log, corpus=corpus, rail=FakeRail({"error": "timeout"}),
                       today=NOW.date()) == 1
    assert not corpus.exists() or not list(corpus.iterdir())


def test_max_days_limits_one_run(tmp_path):
    log, corpus = tmp_path / "h.jsonl", tmp_path / "corpus"
    for d in (18, 19, 20, 21):
        h.record("q", "a", path=log, now=dt.datetime(2026, 10, d, 9, tzinfo=UTC))
    h.summarize(log=log, corpus=corpus, rail=FakeRail({"text": "- x"}), today=NOW.date(),
                max_days=2)
    assert sorted(p.name for p in corpus.iterdir()) == ["telegram-2026-10-18.md",
                                                         "telegram-2026-10-19.md"]


def test_gateway_wires_history_in_and_out():
    text = (Path(__file__).resolve().parents[1] / "scripts" / "telegram-gateway-poll.sh").read_text()
    assert "import tg_history" in text
    assert "tg_history.with_context(routed_text)" in text
    # Recorded after redaction, before HTML escaping.
    rec = text.index("tg_history.record(routed_text, response")
    assert text.index("response = scan_output(response)") < rec < text.index(
        "response = escape_html_response(response)")

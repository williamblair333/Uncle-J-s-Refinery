"""Tests for scripts/meta_questions.py: Bill's meta-questions counted per session, per week.

A meta-question is Bill asking why the agent didn't anticipate something ("why didn't you…",
"why did I have to ask", "is this the best approach", "why not from the get-go"). It is the
outcome metric for STANDARDS.md `meta-question-rate`. Transcripts here are synthetic."""
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location("meta_questions", REPO / "scripts/meta_questions.py")
mq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mq)


# ── what counts as a meta-question ──────────────────────────────────────────

@pytest.mark.parametrize("prompt", [
    "why didn't you check the log first?",
    "Why did you not run the tests",
    "why did I have to ask for that",
    "why do I have to tell you every time",
    "is this the best approach?",
    "is that the best way to do it",
    "why not from the get-go?",
    "why wasn't that done from the start",
    "how come you didn't run the tests",
    "you should have caught that already",
    "why are you asking me?",
    "did you even check?",
    # paraphrases of misses found in a 76-prompt sample of real transcripts (2026-10-31)
    "i'm wondering why you failed to do this from the get go",
    "is all this the best approach",
    "go ahead but tell me why I had to ask for you to find this",
    "why keep asking me? we're collaborating",
    "I thought you'd be reminding me of that too",
    "so many things you're not reminding me of",
    "why wasn't it in the list you gave earlier",
    "the server should always do this, why isn't it then",
    "did you not consider writing a test first",
    "why can't you work these things out on your own",
    "you should have notes from the last session",
    "I'm confused why you did all this without asking me first",
    "looks stuck again, I thought that was fixed",
    "why did you suggest that?",
    "tell me why you didn't include the other model",
    "explain why you don't have the tools to know what I ask before I ask",
    "it went fine. also can't you do this on your own",
    "maybe you should find a way to do that on your own",
    'why didn\'t you check "the log" first',  # quotes elsewhere don't hide the question
    "you didn't restart the game after it failed - why?",
    "screen is stuck again, why, thought was fixed",
    "why not use a docker container then",
])
def test_meta_questions_match(prompt):
    assert mq.is_meta(prompt)


@pytest.mark.parametrize("prompt", [
    "why does the cron fail?",
    "why is CI red",
    "fix the referee retry",
    "what's the best approach for caching?",
    "",
    # ordinary "why" questions from the same sample: about the world, not the agent
    "why is it taking so long",
    "why does it take 10 hours to print",
    "why would google do that",
    "why isn't it working",
    "find out why the system is so slow",
    "ok so I should have computer moves ticked right?",
    "why does it only pick one number",
    # false hits found when checking precision (3 of 27 on 2026-W43/W44)
    "keep going on your own",                                   # an instruction
    'next: count your "why didn\'t you…" questions per week',   # the phrase quoted, not asked
    "❯ why aren't you doing it?\n● You're right, I should have",  # a pasted old exchange
])
def test_ordinary_questions_do_not_match(prompt):
    assert not mq.is_meta(prompt)


@pytest.mark.parametrize("prompt", [
    "<command-name>/foo</command-name> why didn't you",
    "Base directory for this skill: x\nwhy didn't you",
    "[Request interrupted by user] why didn't you",
    "<task-notification> why didn't you </task-notification>",
    "Stop hook feedback:\nwhy didn't you",
    "x" * 1600 + " why didn't you",  # a paste, not a question Bill typed
])
def test_injected_or_pasted_text_is_not_bill_asking(prompt):
    assert not mq.is_meta(prompt)


# ── weekly counts from transcripts ──────────────────────────────────────────

def user(text, ts, **extra):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}, **extra}


def tool_result(ts):
    return {"type": "user", "timestamp": ts,
            "message": {"content": [{"type": "tool_result", "content": "why didn't you"}]}}


def assistant(text, ts):
    return {"type": "assistant", "timestamp": ts,
            "message": {"content": [{"type": "text", "text": text}]}}


def write(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n\nnot json\n")
    return path


@pytest.fixture
def transcripts(tmp_path):
    # 2026-10-27 is ISO 2026-W44; 2026-10-20 is W43.
    a = write(tmp_path / "proj-a" / "s1.jsonl", [
        user("fix the bug", "2026-10-27T09:00:00Z"),
        assistant("why didn't you say so", "2026-10-27T09:01:00Z"),  # assistant text never counts
        user("why didn't you run the tests?", "2026-10-27T09:05:00Z"),
        tool_result("2026-10-27T09:06:00Z"),                        # tool output never counts
        user("why did I have to ask", "2026-10-27T09:07:00Z", isMeta=True),  # harness meta entry
        user("why didn't you check", "2026-10-27T09:08:00Z", isSidechain=True),  # subagent
    ])
    b = write(tmp_path / "proj-b" / "s2.jsonl", [
        user("is this the best approach?", "2026-10-28T10:00:00Z"),
        user("ok go", "2026-10-28T10:05:00Z"),
    ])
    c = write(tmp_path / "proj-a" / "s3.jsonl", [
        user("why not from the get-go?", "2026-10-20T10:00:00Z"),
    ])
    empty = write(tmp_path / "proj-a" / "s4.jsonl", [assistant("hi", "2026-10-27T10:00:00Z")])
    return [a, b, c, empty]


def test_weekly_counts_sessions_prompts_and_meta(transcripts):
    weeks = mq.weekly(transcripts)
    assert weeks["2026-W44"] == {"sessions": 2, "prompts": 4, "meta": 2}
    assert weeks["2026-W43"] == {"sessions": 1, "prompts": 1, "meta": 1}
    assert set(weeks) == {"2026-W43", "2026-W44"}  # a transcript with no Bill prompt adds nothing


def test_hits_carry_week_project_and_prompt(transcripts):
    hits = mq.hits(transcripts)
    assert {(h["week"], h["project"], h["prompt"]) for h in hits} == {
        ("2026-W44", "proj-a", "why didn't you run the tests?"),
        ("2026-W44", "proj-b", "is this the best approach?"),
        ("2026-W43", "proj-a", "why not from the get-go?"),
    }


# ── the Monday line ─────────────────────────────────────────────────────────

MONDAY = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)  # last complete week: 2026-W44


def test_report_line_compares_last_week_with_the_four_before():
    weeks = {
        "2026-W44": {"sessions": 4, "prompts": 40, "meta": 2},   # 0.50/session
        "2026-W43": {"sessions": 2, "prompts": 10, "meta": 2},   # 1.00
        "2026-W42": {"sessions": 2, "prompts": 10, "meta": 0},   # 0.00
        "2026-W41": {"sessions": 2, "prompts": 10, "meta": 2},   # 1.00
        "2026-W40": {"sessions": 2, "prompts": 10, "meta": 0},   # 0.00
        "2026-W39": {"sessions": 1, "prompts": 10, "meta": 9},   # outside the 4-week window
        "2026-W45": {"sessions": 9, "prompts": 10, "meta": 9},   # the current, unfinished week
    }
    line = mq.report_line(weeks, MONDAY)
    assert "2 in 4 sessions" in line
    assert "0.50/session" in line
    assert "4-week average 0.50" in line  # mean of per-session rates (1 + 0 + 1 + 0) / 4
    assert line.endswith("flat.")


@pytest.mark.parametrize("meta, word", [(1, "down."), (4, "up.")])
def test_report_line_trend_word(meta, word):
    weeks = {"2026-W44": {"sessions": 4, "prompts": 40, "meta": meta},
             "2026-W43": {"sessions": 4, "prompts": 40, "meta": 2}}
    assert mq.report_line(weeks, MONDAY).endswith(word)


def test_report_line_with_no_history_has_no_trend():
    line = mq.report_line({"2026-W44": {"sessions": 3, "prompts": 9, "meta": 0}}, MONDAY)
    assert "0 in 3 sessions" in line
    assert "average" not in line


def test_report_line_with_no_sessions_last_week():
    assert "no sessions" in mq.report_line({}, MONDAY)


# ── CLI ─────────────────────────────────────────────────────────────────────

def run_cli(*args):
    return subprocess.run([sys.executable, str(REPO / "scripts/meta_questions.py"), *args],
                          capture_output=True, text=True)


def test_cli_line(transcripts):
    r = run_cli("--line", "--now", "2026-11-02", "--files", *map(str, transcripts))
    assert r.returncode == 0, r.stderr
    assert "2 in 2 sessions" in r.stdout
    assert r.stdout.strip().endswith("flat.")  # 1.00/session in W44 vs 1.00 in W43


def test_cli_table_and_out(transcripts, tmp_path):
    out = tmp_path / "hits.jsonl"
    r = run_cli("--now", "2026-11-02", "--out", str(out), "--files", *map(str, transcripts))
    assert r.returncode == 0, r.stderr
    assert "2026-W44" in r.stdout and "2026-W43" in r.stdout
    assert len(out.read_text().splitlines()) == 3

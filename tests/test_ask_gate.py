"""scripts/ask_gate.py: a turn that ends asking permission for agreed work gets one forced retry."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
SCRIPT = REPO / "scripts" / "ask_gate.py"
HOOK = REPO / "hooks" / "discipline" / "ask-gate.sh"
_spec = importlib.util.spec_from_file_location("ask_gate", SCRIPT)
ag = importlib.util.module_from_spec(_spec)
sys.path.insert(0, str(REPO / "scripts"))
_spec.loader.exec_module(ag)

# Real turn endings from transcripts. The first is the mtw2 turn Bill complained about, 2026-11-06.
ASKS = [
    "It would also help `forced-events`, one of the phase's open standards. Want me to look into "
    "it while the live run plays?",
    "Want me to find where the generator emits this pattern and fix it across the decks?",
    "Shall I start with the FW2/FW3 scorers?",
    "Should I do both?",
    "Do you want me to keep it going while I fix the false move reports?",
    "Would you like me to run it now?",
    "Tests pass.\n\nWant me to do that as a PR?",
    "I can add the bench too. Let me know if you'd like that.",
    "The next step is the bench. Say the word and I'll start.",
    "If you want, I can write the test.",
]
# Bill's to decide, or no ask at all.
QUIET = [
    "Should I merge PR #38 now, or wait until you've printed the coupons?",
    "Want me to push it?",
    "Shall I delete the old index?",
    "Should I post the reply?",
    "Want me to order the boards?",
    "Fixed it. The bench passes on all 12 saves.",
    "Why did the Pope die on turn 30?",
    "Which one do you mean, the wife offer or the suitor offer?",
    # a quoted ask is a mention, not this turn's ask
    'The session ended with "Want me to look into it?"',
    "Bench is green.\n\n```\nWant me to retry?\n```",
    # an earlier sentence asked, but the turn went on and did the work
    "Want me to fix it? Doing it now since it's cheap. Fixed, tests pass.",
]


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(ag, "LOG", tmp_path / "ask-gate.jsonl")
    monkeypatch.delenv("ASK_GATE", raising=False)
    monkeypatch.delenv("ASK_GATE_LOG", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")


@pytest.mark.parametrize("text", ASKS)
def test_permission_asks_block(text):
    v = ag.decide({"last_assistant_message": text})
    assert v and v["decision"] == "block"


@pytest.mark.parametrize("text", QUIET)
def test_real_decisions_and_plain_replies_pass(text):
    assert ag.decide({"last_assistant_message": text}) is None


def test_reason_quotes_the_ask_and_keeps_the_way_out():
    r = ag.decide({"last_assistant_message": ASKS[1]})["reason"]
    assert "find where the generator" in r
    assert "start it now" in r and "Bill's call" in r and "better way" in r
    assert "analysis, a draft or a review" in r   # "analyze X" must not turn into building X


def test_a_blockquote_does_not_hide_the_ask_below_it():
    assert ag.final_ask("> quoted line\nmore text.\n\nWant me to run the bench?")


# Referee (Gemini) findings on b012ac8, each reproduced here before the fix.
@pytest.mark.parametrize("text", [
    "Want me to run `git push`?",
    'Should I run "git reset --hard"?',
    "Tests pass. Want me to run `rm -rf build && git push origin main`?",
])
def test_an_outward_command_in_backticks_still_passes(text):
    assert ag.decide({"last_assistant_message": text}) is None


def test_backticked_harmless_ask_still_blocks():
    assert ag.decide({"last_assistant_message": "Want me to run `just test`?"})


def test_a_word_in_an_earlier_sentence_does_not_exempt_the_ask():
    assert ag.decide({"last_assistant_message": "I fixed the push bug. Want me to run the bench?"})


@pytest.mark.parametrize("bad", [123, ["x"], {"a": 1}, True])
def test_a_non_string_message_never_crashes(bad):
    assert ag.decide({"last_assistant_message": bad}) is None


@pytest.mark.parametrize("text", [
    "Want me to look into it\nwhile the live run plays?",
    "Done\nWant me to run the bench?",
    "All green.\n\nShould I start\non the next item?",
])
def test_an_ask_wrapped_over_lines_still_blocks(text):
    assert ag.decide({"last_assistant_message": text})


def test_blocks_only_once():
    assert ag.decide({"last_assistant_message": ASKS[1], "stop_hook_active": True}) is None


def test_kill_switch_and_headless(monkeypatch):
    monkeypatch.setenv("ASK_GATE", "off")
    assert ag.decide({"last_assistant_message": ASKS[1]}) is None
    monkeypatch.delenv("ASK_GATE")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    assert ag.decide({"last_assistant_message": ASKS[1]}) is None


def test_reads_the_transcript_when_the_hook_has_no_message(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join(json.dumps(e) for e in [
        {"type": "user", "message": {"content": "go"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": ASKS[1]}]}},
    ]) + "\n")
    assert ag.decide({"transcript_path": str(t)})


def test_replay_counts_asks_and_the_replies_they_got(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join(json.dumps(e) for e in [
        {"type": "user", "message": {"content": "look at this"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": ASKS[1]}]}},
        {"type": "user", "message": {"content": "yes"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": ASKS[2]}]}},
        {"type": "user", "message": {"content": "no, not that"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done."}]}},
        {"type": "user", "message": {"content": "thanks"}},
    ]) + "\n")
    r = ag.replay([t])
    assert (r["turn_ends"], r["fired"], r["replied_yes"], r["replied_no"]) == (3, 2, 1, 1)


def test_hook_script_blocks_and_fails_open(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "CLAUDE_CODE_ENTRYPOINT": "cli",
           "ASK_GATE_LOG": str(tmp_path / "log.jsonl")}
    r = subprocess.run(["bash", str(HOOK)], input=json.dumps({"last_assistant_message": ASKS[1]}),
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0 and json.loads(r.stdout)["decision"] == "block"
    logged = (tmp_path / "log.jsonl").read_text()
    assert "generator" not in logged          # counts only, no reply text
    r = subprocess.run(["bash", str(HOOK)], input="not json", capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout == ""

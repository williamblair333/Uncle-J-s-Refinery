"""features/prompt-triggers/meta_trigger.py: Bill's "why did I have to catch this" prompts force a real fix."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "features" / "prompt-triggers" / "meta_trigger.py"
sys.path.insert(0, str(SCRIPT.parent))
sys.path.insert(0, str(REPO / "scripts"))
import meta_trigger as mt  # noqa: E402

# Bill's own words, 2026-11-01 (mtw2 session and this one).
HITS = [
    "why did i have to request this!! you could have should have seen this possibility",
    "you should have caught that before running it",
    "why didn't you think of that",
    "i'm tired of having to solve the problems all the time",
    "before you continue, tell me if mtw2 is using the new skills? cause it still can't figure "
    "shit out. latest example:  why did i have to request this!!\n\n"
    "● You're right, and it was there to see. The handoff already called papal elections the "
    "main crash source.\n  So it doesn't depend on you asking again, I'm saving it as standing "
    "guidance:  i'm tired of having to solve the problems all the time",
    "this is what i was talking about before.  any project manager would be smart enough to see "
    "that if something is slowing down a process or test, fix it, mitigate it, something..",
    # mtw2 drift, 2026-11-01: both went unflagged
    "have you tested everything that doesn't require a click now? if not, why are you doing this?",
    "are you drifting from the goal and how to get there? are you using the new skills we built?  "
    "would you check yourself while the other process runs?",
    "I'm getting frustrated you know",
    # Klarheit, 2026-11-04: went unflagged
    "This infuriates me.  I have worked hard for Uncle J / you to think of things like this.  "
    "There are skills involved that are supposed to kick in . and they didn't.",
    "the skills are supposed to kick in and they didn't",
    "OK.  I had this conversation in Klarheit and why didn't the fucking skills fire",
]
ORDER_HITS = [
    "from last session  First up next session:\n  1. Quiet world for turn tests\n  2. Far boarding",
    "continue",
    "what's next?",
    "just-do-it so long as this is moving towards our goal",
    "**Next (in order):** 1. the quiet world; 2. prove and merge far-board",
]
ORDER_MISSES = [
    "build it",
    "continue the qa run after the pope fix lands",
    "what's the status of the qa run?",
    "<task-notification> continue </task-notification>",
    # sign-offs, bench 2026-11-01
    "session end I'll read this next session",
    "session end pick up next session",
    "ok put firecrawl in review and we'll have you dig into it next session.",
    "fyi Uncle J is working on some agy struggles and hopefully will be better next session",
]
MISSES = [
    "build it",
    "do it but also how do we make this unverisal for all project / sessions",
    "what's the status of the qa run?",
    "can you make it so a pope doesn't die while you're testing?",
    # pasted agent text full of "you should have", with nothing from Bill after it
    "● You should have seen the log. Why didn't you check it? That was my miss.",
    "<task-notification> why didn't you check </task-notification>",
    # a peer session's message is not Bill's complaint (2026-11-04)
    '<cross-session-message from="uds:/x.sock">why didn\'t the skills fire? I\'m frustrated'
    "</cross-session-message>",
    "the skills dir has 90 entries",
]


@pytest.mark.parametrize("prompt", HITS)
def test_complaints_trigger(prompt):
    assert mt.triggered(prompt)


@pytest.mark.parametrize("prompt", MISSES)
def test_ordinary_prompts_do_not(prompt):
    assert not mt.triggered(prompt)


@pytest.mark.parametrize("prompt", ORDER_HITS)
def test_order_prompts_trigger_order_check(prompt):
    assert mt.order_triggered(prompt)


@pytest.mark.parametrize("prompt", ORDER_MISSES)
def test_order_check_quiet_otherwise(prompt):
    assert not mt.order_triggered(prompt)


def test_hook_joins_both_messages_when_both_fire():
    r = run(json.dumps({"prompt": "from last session First up: 1. x. why are you doing this?"}))
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "expert-bar" in ctx and "STANDARDS.md phase line" in ctx


def run(stdin: str):
    return subprocess.run([sys.executable, str(SCRIPT)], input=stdin, capture_output=True, text=True)


def test_hook_emits_expert_bar_and_mechanical_fix():
    r = run(json.dumps({"prompt": HITS[0]}))
    assert r.returncode == 0
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "expert-bar" in ctx and "preflight.toml" in ctx and "memory note" in ctx


def test_hook_silent_on_miss_and_garbage():
    assert run(json.dumps({"prompt": "build it"})).stdout == ""
    r = run("not json")
    assert r.returncode == 0 and r.stdout == ""

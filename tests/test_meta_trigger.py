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
]
MISSES = [
    "build it",
    "do it but also how do we make this unverisal for all project / sessions",
    "what's the status of the qa run?",
    "can you make it so a pope doesn't die while you're testing?",
    # pasted agent text full of "you should have", with nothing from Bill after it
    "● You should have seen the log. Why didn't you check it? That was my miss.",
    "<task-notification> why didn't you check </task-notification>",
]


@pytest.mark.parametrize("prompt", HITS)
def test_complaints_trigger(prompt):
    assert mt.triggered(prompt)


@pytest.mark.parametrize("prompt", MISSES)
def test_ordinary_prompts_do_not(prompt):
    assert not mt.triggered(prompt)


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

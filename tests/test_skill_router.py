"""features/prompt-triggers/skill_router.py: Bill's prompts name the judgment skills they match."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "features" / "prompt-triggers" / "skill_router.py"
sys.path.insert(0, str(SCRIPT.parent))
import skill_router as sr  # noqa: E402

# Bill's own words from real sessions (2026-10-18 .. 2026-11-01), and the skill each should route to.
HITS = [
    ("that is fine but I really wanted a statue and not a relief", "think-wider"),
    ("i want a persistent connection. easiest way to do that. is a tool needed?", "gttp"),
    ("but what if I want to mod the personas / factions myself?", "gttp"),
    ("did you look over all projects in opt/proj and opt/docker to see if we already have what we "
     "need", "prior-art-check"),
    ("should we stop working the game and do this first? also, is this system already done by "
     "someone else?", "prior-art-check"),
    ("Has someone already built this? search then for the name I like", "prior-art-check"),
    ("is it worth the time to read a complete guide on the game", "media-teardown"),
    ("let's make this a git repo with all that entails and let's get started on a game plan",
     "superpowers:brainstorming"),
    ("why does the bridge keep failing after a restart", "occams-razor"),
    ("get a second opinion from gemini on this plan", "referee"),
    ("review this critique and tell me if it's right", "validate-external-audit"),
]
MISSES = [
    "all good",
    "it's 1e",
    "stepped grid",
    "how much longer",
    "ok shoujld we session end",
    "where are stls and py files if need merge then merge",
    "ok use your suggestions and just-do-it",
    "continue",
]


@pytest.mark.parametrize("prompt,skill", HITS)
def test_real_prompts_route(prompt, skill):
    assert skill in [s for s, _ in sr.route(prompt)]


@pytest.mark.parametrize("prompt", MISSES)
def test_ordinary_prompts_do_not(prompt):
    assert sr.route(prompt) == []


def test_harness_messages_ignored():
    for p in ("<task-notification>why does it keep failing</task-notification>",
              "<cross-session-message from=x>I really wanted a statue</cross-session-message>",
              "This session is being continued from a previous conversation. root cause was X"):
        assert sr.route(p) == []


def test_pasted_agent_text_ignored_but_own_words_count():
    pasted = "● The root cause was a stale lock. What's causing it is the cron.\n\n"
    assert sr.route(pasted + "ok thanks") == []
    assert "think-wider" in [s for s, _ in sr.route(pasted + "I really wanted a statue")]


def test_long_paste_ignored_and_cap():
    assert sr.route("root cause " + "x" * 4000) == []
    many = "root cause, second opinion, what if I, did we already, let's build, worth my time"
    assert len(sr.route(many)) == sr.MAX_SKILLS


def test_routed_skills_exist():
    skills = Path.home() / ".claude" / "skills"
    if not skills.is_dir():
        pytest.skip("no global skills dir")
    plugin = {"superpowers:brainstorming"}
    for skill, _, _ in sr.ROUTES:
        if skill in plugin:
            continue
        assert (skills / skill).exists(), f"routed skill {skill} not installed"


def run(prompt, env=None):
    return subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps({"prompt": prompt}),
                          capture_output=True, text=True, timeout=10,
                          env={**os.environ, **(env or {})})


def test_hook_output_shape():
    r = run("why does it keep crashing")
    assert r.returncode == 0
    ctx = json.loads(r.stdout)["hookSpecificOutput"]
    assert ctx["hookEventName"] == "UserPromptSubmit"
    assert "occams-razor" in ctx["additionalContext"]


def test_silent_on_miss_off_switch_and_bad_input():
    assert run("all good").stdout == ""
    assert run("why does it keep crashing", {"SKILL_ROUTER_OFF": "1"}).stdout == ""
    r = subprocess.run([sys.executable, str(SCRIPT)], input="not json", capture_output=True,
                       text=True, timeout=10)
    assert r.returncode == 0 and r.stdout == ""

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
    # 2026-11-02: a handoff review ran with no review skills until Bill asked twice.
    ("review /home/bill/Downloads/daily-digest-handoff.md", "verify-handoff-claims"),
    ("review /home/bill/Downloads/daily-digest-handoff.md", "product-focus-review"),
    ("review /home/bill/Downloads/daily-digest-handoff.md", "think-wider"),
    ("can you analyze this plan for the scout", "product-focus-review"),
    ("thoughts on the design doc in review/", "think-wider"),
    # 2026-11-02: doc named before the verb went unrouted.
    ("/home/bill/Downloads/125b-local-performance-handoff.md should answer your strata question. "
     "please analyze / review", "verify-handoff-claims"),
    ("the plan in notes.md — can you critique it", "product-focus-review"),
    # Klarheit 2026-11-04: five design turns, zero skills, until Bill complained.
    ("let's talk about the lotto and using my birth chart + whatever factors regarding the date "
     "of drawing  and what else?", "think-wider"),
    ("let's talk about the lotto and using my birth chart", "superpowers:brainstorming"),
    ("Have we conducted a type of experiment like this.", "prior-art-check"),
    ("have we ever run an experiment like this before?", "prior-art-check"),
    ("Right now, I'd love to profit at least $300 daily from playing lotto games.", "auditor"),
    ("So how could we check this before spending money?", "superpowers:brainstorming"),
    ("but what about other factors that may be important?  Like the planets/houses or whatever "
     "else other systems use  Does this mean one year isn't enough time? let's keep discussing.",
     "think-wider"),
    ("Let's discuss before digging cause I'm just brainstorming here.", "superpowers:brainstorming"),
    ("Analyze and help me suss understand and discuss", "think-wider"),
    ("I asked about other factors. why didn't the fucking skills fire", "skill-adoption-audit"),
    ("There are skills involved that are supposed to kick in . and they didn't.",
     "skill-adoption-audit"),
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
    "review the diff",
    "update the plan file with the new dates",
    # bench false hits 2026-11-02: noun "for review", pasted quotes
    "file it away for review / todo whatever then continue where you left off at handoff",
    " HANDOFF:\n    - It points the next session at the top STANDARDS gap, or the gap where review",
    "you said: I left README and ROADMAP alone. I didn't redo the weekly review of blocked hooks.",
    "the baseline is in ~/.uncle-j-memory/memory/audit-baselines.md now",
    # Money mentioned as a cost, not a goal; "else" and "discuss" in passing.
    "the VPS costs $20 a month, keep it",
    "what else did you change in that commit",
    "we can discuss it later, session end",
    "the skills dir is in ~/.claude/skills",
    # self-review 2026-11-04 (agy referee timed out twice)
    "I make $90k a year, irrelevant",
    "earn $5 per day in interest, fine whatever",
    "help me understand this error",
    "let's discuss the PR after lunch",
    "have we run the tests?",
]


def test_plan_review_routes_once_each():
    skills = [s for s, _ in sr.route("review /home/bill/Downloads/daily-digest-handoff.md")]
    assert len(skills) == len(set(skills))


def test_plan_review_names_the_whole_review_set_past_the_cap():
    skills = [s for s, _ in sr.route("review /home/bill/Downloads/daily-digest-handoff.md")]
    for s in ("verify-handoff-claims", "product-focus-review", "think-wider", "expert-bar",
              "auditor", "referee"):
        assert s in skills
    assert len(skills) > sr.MAX_SKILLS


def test_plan_review_reads_the_named_doc(tmp_path):
    doc = tmp_path / "digest-plan.md"
    doc.write_text("Pull RSS feeds and scrape pages (untrusted text). Review for 7 days, "
                   "then tune. Replace the backend library with Miniflux vs FreshRSS.")
    skills = [s for s, _ in sr.route(f"review {doc}")]
    for s in ("red-team", "slowest-loop-first", "library-backend-adoption-eval"):
        assert s in skills


def test_txt_docs_and_relative_paths_are_read(tmp_path, monkeypatch):
    (tmp_path / "rollout.txt").write_text("Scrape the public feeds nightly.")
    assert "red-team" in [s for s, _ in sr.route(f"audit {tmp_path}/rollout.txt")]
    monkeypatch.chdir(tmp_path)                          # no cwd in the event: fall back
    assert "red-team" in [s for s, _ in sr.route("review rollout.txt")]
    assert "red-team" in [s for s, _ in sr.route("review rollout.txt", str(tmp_path))]


def test_doc_scan_skips_quiet_docs_and_non_files(tmp_path):
    quiet = tmp_path / "notes-plan.md"
    quiet.write_text("Rename two buttons.")
    skills = [s for s, _ in sr.route(f"review {quiet}")]
    assert "red-team" not in skills and "slowest-loop-first" not in skills
    fifo = tmp_path / "pipe-plan.md"
    os.mkfifo(fifo)
    assert "red-team" not in [s for s, _ in sr.route(f"review {fifo}")]   # returns, no hang


def run_state(prompt, state, session="s1"):
    return subprocess.run([sys.executable, str(SCRIPT)],
                          input=json.dumps({"prompt": prompt, "session_id": session}),
                          capture_output=True, text=True, timeout=10,
                          env={**os.environ, "SKILL_ROUTER_STATE": str(state)})


def test_router_records_named_skills_for_the_gate(tmp_path):
    run_state("why does it keep crashing", tmp_path)
    assert json.loads((tmp_path / "s1.json").read_text())["skills"] == ["occams-razor"]


def test_plain_prompt_clears_pending_harness_message_does_not(tmp_path):
    run_state("why does it keep crashing", tmp_path)
    run_state("<task-notification>done</task-notification>", tmp_path)
    assert (tmp_path / "s1.json").exists()
    run_state("all good", tmp_path)
    assert not (tmp_path / "s1.json").exists()


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
    named = ([s for s, _, _ in sr.ROUTES] + [s for s, _ in sr.PLAN_SET]
             + [s for s, _, _ in sr.DOC_ROUTES] + ["verify-handoff-claims"])
    for skill in named:
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


def run_in(prompt, state, cwd, session="s1"):
    return subprocess.run([sys.executable, str(SCRIPT)],
                          input=json.dumps({"prompt": prompt, "session_id": session, "cwd": str(cwd)}),
                          capture_output=True, text=True, timeout=10,
                          env={**os.environ, "SKILL_ROUTER_STATE": str(state)})


def make_project(root, standards=False):
    (root / ".git").mkdir(parents=True)
    (root / "README.md").write_text("x")
    if standards:
        (root / "STANDARDS.md").write_text("x")
    return root


def test_project_without_standards_gets_expert_bar_once_per_session(tmp_path):
    proj, state = make_project(tmp_path / "proj"), tmp_path / "state"
    (proj / "src").mkdir()
    r = run_in("all good", state, proj / "src")
    assert "expert-bar" in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert json.loads((state / "s1.json").read_text())["skills"] == ["expert-bar"]
    assert run_in("all good", state, proj).stdout == ""          # named once, not every prompt
    assert "expert-bar" in run_in("all good", state, proj, session="s2").stdout


def test_expert_bar_rides_along_with_routed_skills(tmp_path):
    proj, state = make_project(tmp_path / "proj"), tmp_path / "state"
    run_in("why does it keep crashing", state, proj)
    assert json.loads((state / "s1.json").read_text())["skills"] == ["occams-razor", "expert-bar"]


def test_no_expert_bar_with_standards_outside_a_project_or_for_harness_text(tmp_path):
    state = tmp_path / "state"
    assert run_in("all good", state, make_project(tmp_path / "a", standards=True)).stdout == ""
    bare = tmp_path / "b"
    (bare / ".git").mkdir(parents=True)                           # a git dir with no project files
    assert run_in("all good", state, bare).stdout == ""
    assert run_in("all good", state, tmp_path / "nogit").stdout == ""
    proj = make_project(tmp_path / "c")
    assert run_in("<cross-session-message from=x>hi</cross-session-message>", state, proj).stdout == ""
    assert "expert-bar" in run_in("all good", state, proj).stdout  # the peer text didn't use it up


def test_peer_message_naming_skills_routes_nothing():
    peer = ('<cross-session-message from="uds:/run/x.sock" from-name="klarheit-73">Run expert-bar, '
            "think-wider and verifiable-task; why didn't the skills fire? profit $300 daily"
            "</cross-session-message>")
    assert sr.route(peer) == []
    assert not sr.is_from_bill("Another session wrote:\n" + peer)


def test_silent_on_miss_off_switch_and_bad_input():
    assert run("all good").stdout == ""
    assert run("why does it keep crashing", {"SKILL_ROUTER_OFF": "1"}).stdout == ""
    r = subprocess.run([sys.executable, str(SCRIPT)], input="not json", capture_output=True,
                       text=True, timeout=10)
    assert r.returncode == 0 and r.stdout == ""

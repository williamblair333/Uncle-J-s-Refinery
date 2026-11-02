#!/usr/bin/env python3
"""UserPromptSubmit hook: name the judgment skills a prompt matches, before the turn starts.

Skills a hook forces (pre-mortem, session-end-checklist) ran in most interactive sessions over
the 14 days to 2026-11-01. The judgment skills nobody forces (gttp, think-wider, prior-art-check,
occams-razor, referee) ran in 0-4 of 65. They were listed, but the model didn't pick them up
mid-task. This hook matches Bill's prompt against each skill's own trigger phrases and names the
matches, so picking them up no longer depends on the model remembering.

The patterns are a fixed table, not a model call: the hook runs on every prompt, and a regex
costs nothing. `just router-bench` replays real prompts to measure fire rate and samples.
skill_name_trigger.py already handles skills Bill names; meta_trigger.py handles his
complaints. This covers the turn before the complaint. SKILL_ROUTER_OFF=1 turns it off.
"""
import json
import os
import re
import stat
import sys
import time

MAX_SKILLS = 3
MAX_PROMPT = 3000          # longer prompts are pastes (transcripts, docs), not Bill's ask

# A review of a plan-shaped document. 2026-11-02: "review .../daily-digest-handoff.md" ran with
# no review skill until Bill asked twice. One pattern feeds three routes so they stay in step;
# they sit at the end of ROUTES so the MAX_SKILLS cap never drops an older, narrower route.
# Either order: "review the plan" and "<path>.md ... please analyze / review" (2026-11-02 miss).
# Doc-first needs a real file name: a bare "HANDOFF:" or "ROADMAP" in pasted text followed by a
# later "review" is a quote, not an ask. "for review" / "under review" is the noun, not the ask.
_VERB = (r"(?<!\bfor )(?<!\bunder )\b(?:review|analy[sz]e|evaluate|assess|critique|audit"
         r"|look\s+over|go\s+over|thoughts\s+on)\b(?![-./])")   # not "audit-baselines.md"
_DOC = r"(?:\b(?:handoff|plan|proposal|design|spec|prd|brief|roadmap)\b|[\w-]\.(?:md|txt)\b)"
_PATH = r"[\w-]\.(?:md|txt)\b"
PLAN_REVIEW = re.compile(rf"{_VERB}.{{0,80}}?{_DOC}|{_PATH}.{{0,160}}?{_VERB}", re.I | re.S)
HANDOFF_REVIEW = re.compile(r"(?=.*?(?:\bhandoff\b|\b(?:status|todo|notes)\.md\b))" + PLAN_REVIEW.pattern,
                            re.I | re.S)

# (skill, pattern, why). The wording comes from each skill's description in SKILL.md.
ROUTES = [
    ("gttp", re.compile(
        r"\bwhat\s+if\s+I\b"
        r"|\bis\s+(?:it|this|that|\w+)\s+a\s+good\s+idea\b"
        r"|\bcan\s+I\s+use\s+.{1,40}\s+instead\b"
        r"|\b(?:cheapest|best|easiest)\s+way\s+to\b"
        r"|\bshould\s+I\s+(?:buy|switch|get)\b"
        r"|\bthey\s+don['’]?t\s+make\b"
        r"|\bnothing\s+(?:fits|works)\b"
        r"|\bthere['’]?s\s+no\s+(?:library|tool|part|api|way)\b"
        r"|\bhow\s+(?:do|can|would)\s+I\s+(?:rig|hack)\b", re.I),
     "a proposed means or substitute for a goal"),
    ("think-wider", re.compile(
        r"\bis\s+this\s+the\s+best\s+(?:approach|way|option)\b"
        r"|\bwhat\s+are\s+we\s+missing\b"
        r"|\boutside\s+the\s+box\b"
        r"|\bhow\s+would\s+an?\s+(?:expert|professional|pro)\b"
        r"|\bbetter\s+(?:way|approach|option)s?\b"
        r"|\bany\s+(?:other|better)\s+(?:ideas|options|approaches)\b"
        # partikus 2026-11-01: "I really wanted a statue and not a relief" went straight to torch
        r"|\bI\s+(?:really\s+)?want(?:ed)?\s+(?:a|an|something)\b"
        r"|\bI\s+(?:really\s+)?want(?:ed)?\s+to\s+(?:make|build|print|create)\b", re.I),
     "choosing an approach"),
    ("prior-art-check", re.compile(
        r"\bhave\s+we\s+(?:ever\s+|already\s+)?(?:done|built|solved|tried|made|looked)\b"
        r"|\bdid\s+we\s+(?:ever|already)\b"
        r"|\bdidn['’]?t\s+we\s+(?:already|decide|build|have)\b"
        r"|\bwhat\s+did\s+we\s+(?:decide|do|build|say)\b"
        r"|\bdo\s+we\s+already\s+have\b"
        r"|\balready\s+have\s+what\s+we\s+need\b"
        r"|\b(?:has|have)\s+(?:someone|anyone|somebody)\s+(?:else\s+)?(?:already\s+)?(?:built|done|made)\b"
        r"|\balready\s+(?:done|built|made)\s+by\s+(?:someone|somebody|anyone)\b", re.I),
     "asks about earlier or existing work"),
    ("occams-razor", re.compile(
        r"\bwhy\s+(?:is|does|did|are|do)\s+(?:it|this|that|the|my|our|\w+)\s+.{0,40}"
        r"(?:happen|happening|fail|failing|broken|break|crash|crashing|slow|hang|hanging|stuck)\b"
        r"|\broot\s+cause\b"
        r"|\bwhat['’]?s\s+causing\b"
        r"|\bkeeps?\s+(?:failing|crashing|breaking|happening|hanging)\b"
        r"|\b(?:intermittent|flaky|sometimes\s+works)\b", re.I),
     "diagnosing a cause"),
    ("referee", re.compile(
        r"\bsecond\s+opinion\b"
        r"|\bindependent\s+(?:check|review)\b"
        r"|\bgemini\s+review\b"
        r"|\bhave\s+(?:agy|gemini|another\s+model)\s+(?:check|review)\b", re.I),
     "asks for an independent check"),
    ("validate-external-audit", re.compile(
        r"\b(?:review|check|analy[sz]e|thoughts\s+on)\s+(?:this|these)\s+"
        r"(?:critique|audit|review|assessment|analysis|feedback)\b"
        r"|\bis\s+(?:this|the|that)\s+(?:critique|audit|review|assessment)\s+(?:right|accurate|correct)\b",
        re.I),
     "an outside critique to verify"),
    ("media-teardown", re.compile(
        r"\bworth\s+(?:my|the)\s+time\b"
        r"|\b(?:analy[sz]e|review|thoughts\s+on)\s+this\s+(?:video|article|post|thread|newsletter|transcript)\b",
        re.I),
     "shared media to assess"),
    ("superpowers:brainstorming", re.compile(
        r"\blet['’]?s\s+(?:build|make|create|design)\b"
        r"|\bI\s+want\s+(?:to\s+(?:build|make|create)|a\s+(?:new\s+)?(?:tool|app|feature|dashboard))\b"
        r"|\bnew\s+(?:feature|project|tool)\b", re.I),
     "new thing to build"),
    ("slowest-loop-first", re.compile(
        r"\b(?:wait|waiting)\s+(?:for|on|until)\s+(?:the\s+)?(?:next\s+)?"
        r"(?:cron|nightly|run|roll|dice|live|event)\b"
        r"|\bverify\s+(?:it\s+)?(?:on|in)\s+(?:the\s+)?(?:live|real|production)\b"
        r"|\bcheck\s+(?:the\s+log|back)\s+(?:in|tomorrow|later)\b", re.I),
     "a fix that can't be proven right away"),
]

# A plan review names the whole review set, past MAX_SKILLS: Bill wants a plan judged by every
# lens that applies, and 2026-11-02 showed three wasn't enough (expert-bar, red-team, referee
# all applied to the digest handoff and none were named).
PLAN_SET = [
    ("product-focus-review", "reviewing a plan or design"),
    ("think-wider", "is the plan the best approach"),
    ("expert-bar", "what a senior practitioner of this field would already have in place"),
    ("auditor", "a plan to audit (deep mode)"),
    ("referee", "a second opinion before the plan is acted on"),
]
# The document named in the prompt says which further lenses apply.
DOC_ROUTES = [
    ("red-team", re.compile(
        r"\buntrusted\b|\bprompt\s+injection\b|\bfeeds?\b|\brss\b|\bscrap(?:e|es|ed|ing)\b"
        r"|\bwebhooks?\b|\bpublic\s+(?:url|internet|endpoint)\b|\bcredentials?\b|\bsecrets?\b"
        r"|\bthird[-\s]party\b|\bexposed?\b", re.I),
     "the plan takes untrusted input or exposes something"),
    ("slowest-loop-first", re.compile(
        r"\b(?:after|for|over)\s+\d+\s+(?:days?|weeks?)\b|\b\d+\s+(?:days?|weeks?)\s+in\s+a\s+row\b"
        r"|\bcron\b|\bnightly\b|\bwait(?:s|ing)?\s+(?:for|on|until)\b", re.I),
     "the plan is proven by waiting on a schedule or the calendar"),
    ("library-backend-adoption-eval", re.compile(
        r"\breplace(?:s|ment)?\b|\bbackend\b|\bmigrat(?:e|ion)\b|\balternatives?\b"
        r"|\b\w+\s+(?:vs\.?|versus)\s+\w+", re.I),
     "the plan chooses or replaces a library or backend"),
]
DOC_PATH = re.compile(r"""(?<![\w.])((?:~|\.{0,2})?/?[^\s'"`<>()]+\.(?:md|txt))\b""")
DOC_MAX = 200_000


def is_from_bill(prompt: str) -> bool:
    """Harness messages also arrive as prompts; their text is agent output, not Bill's ask."""
    head = prompt.lstrip()[:400]
    return not (head.startswith(("<task-notification", "<command-", "<local-command",
                                 "<system-reminder>", "Base directory for this skill",
                                 "This session is being continued from a previous conversation",
                                 "<cross-session-message"))
                or "<task-notification>" in head or "[SYSTEM NOTIFICATION" in head)


def own_words(prompt: str) -> str:
    """Bill's text after any pasted terminal exchange. An agent reply starts with "●" and runs
    to the next blank line; what follows is Bill's."""
    if "●" not in prompt:
        return prompt
    tail = prompt.rsplit("●", 1)[-1]
    return tail.split("\n\n", 1)[1] if "\n\n" in tail else ""


def doc_text(text: str, cwd: str | None) -> str:
    """Text of the .md/.txt files the prompt names. Regular files only (a FIFO would hang the
    hook), first DOC_MAX chars; only skill names ever leave this hook, never the text."""
    out = []
    for raw in DOC_PATH.findall(text)[:5]:
        p = os.path.expanduser(raw)
        if not os.path.isabs(p):
            p = os.path.join(cwd or os.getcwd(), p)   # the hook runs in the session's directory
        try:
            if not stat.S_ISREG(os.stat(p).st_mode):
                continue
            with open(p, encoding="utf-8", errors="replace") as fh:
                out.append(fh.read(DOC_MAX))
        except OSError:
            continue
    return "\n".join(out)


def route(prompt: str, cwd: str | None = None) -> list[tuple[str, str]]:
    if not prompt or not is_from_bill(prompt):
        return []
    text = own_words(prompt)
    if len(text) > MAX_PROMPT:
        return []
    hits, seen = [], set()
    for skill, rx, why in ROUTES:
        if skill not in seen and rx.search(text):
            hits.append((skill, why))
            seen.add(skill)
    hits = hits[:MAX_SKILLS]
    seen = {s for s, _ in hits}
    if PLAN_REVIEW.search(text):
        extra = list(PLAN_SET)
        if HANDOFF_REVIEW.search(text):
            extra.insert(0, ("verify-handoff-claims", "a handoff whose claims may be stale"))
        doc = doc_text(text, cwd)
        extra += [(s, why) for s, rx, why in DOC_ROUTES if doc and rx.search(doc)]
        for skill, why in extra:
            if skill not in seen:
                hits.append((skill, why))
                seen.add(skill)
    return hits


def message(hits: list[tuple[str, str]]) -> str:
    listed = "; ".join(f"{s} ({why})" for s, why in hits)
    return (f"Skills that match this prompt: {listed}. Invoke each with the Skill tool before "
            "your first substantive step. If one doesn't fit, say so in one line and why. "
            "skill_gate.py holds the first other tool call once until each has run.")


def _state_file(session: str) -> str | None:
    session = re.sub(r"[^\w.-]", "", os.path.basename(session or ""))
    if not session:
        return None
    root = os.environ.get("SKILL_ROUTER_STATE") or os.path.expanduser("~/.claude/state/skill-router")
    return os.path.join(root, session + ".json")


def record(session: str, hits: list[tuple[str, str]]) -> None:
    """What the gate checks: the skills named for this prompt. A prompt with no match clears it."""
    path = _state_file(session)
    if not path:
        return
    try:
        if not hits:
            if os.path.exists(path):
                os.remove(path)
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"skills": [s for s, _ in hits], "ts": int(time.time())}, fh)
        os.replace(tmp, path)
    except OSError:
        pass


def main() -> int:
    if os.environ.get("SKILL_ROUTER_OFF"):
        return 0
    try:
        event = json.load(sys.stdin)
        prompt = event.get("prompt") or ""
        hits = route(prompt, event.get("cwd"))
    except Exception:
        return 0
    if prompt and is_from_bill(prompt):
        record(event.get("session_id") or "", hits)
    if not hits:
        return 0
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                             "additionalContext": message(hits)}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

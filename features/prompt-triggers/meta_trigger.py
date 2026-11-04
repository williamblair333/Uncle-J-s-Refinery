#!/usr/bin/env python3
"""UserPromptSubmit hook: when Bill asks why he had to catch something, make the fix mechanical.

"Why did I have to request this", "you should have seen this", "I'm tired of having to solve
the problems": each says the agent missed something it could have seen. Left alone, sessions
answer with an apology and a memory note, which is read only when the model remembers to read
it, so the same miss comes back (mtw2, 2026-11-01: STANDARDS had the rule, the session never
checked it, and it answered Bill's complaint with one more memory note).

This hook detects those prompts with scripts/meta_questions.is_meta (the same detector the
weekly meta-question count uses, so the bench and the trigger agree) plus a few "tired of
having to" phrasings, and tells the model to run expert-bar and land a check a program runs.

Never blocks and never fails loudly: any error means no output.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

# Fatigue phrasings the weekly count leaves out (it measures questions, not complaints).
EXTRA = re.compile(
    r"\b(?:tired|sick)\s+of\s+(?:having\s+to|always|doing|telling|asking|solving)\b"
    r"|\bI\s+(?:always\s+)?(?:have|had)\s+to\s+(?:solve|figure|catch|spot|think\s+of)\b"
    r"|\bcan['’]?t\s+figure\s+(?:shit|anything|it)\s+out\b"
    # "any project manager would be smart enough to see that…" (2026-11-01)
    r"|\b(?:any|a\s+(?:real|good|senior))\s+(?:project\s+manager|manager|engineer|expert|senior|pm|lead|professional)\s+would\b"
    r"|\bsmart\s+enough\s+to\s+(?:see|know|notice|realize|figure)\b"
    r"|\bthis\s+is\s+what\s+I\s+was\s+talking\s+about\b"
    # mtw2, 2026-11-01: both drift complaints went unflagged
    r"|\bwhy\s+are\s+you\s+(?:even\s+)?(?:doing|working\s+on|building)\s+(?:this|that|it)\b"
    r"|\bdrift(?:ing|ed)?\s+(?:away\s+)?from\s+the\s+(?:goal|plan|task)\b"
    r"|\bare\s+you\s+(?:even\s+)?using\s+the\s+(?:new\s+)?skills\b"
    r"|\bI['’]?m\s+(?:getting\s+)?(?:really\s+|so\s+)?frustrated\b"
    # Klarheit 2026-11-04: "This infuriates me. I have worked hard for Uncle J / you to think of
    # things like this. There are skills involved that are supposed to kick in. and they didn't."
    r"|\binfuriat(?:es|ing|ed)\b"
    r"|\bI\s*(?:['’]ve|\s+have)\s+worked\s+(?:so\s+|really\s+)?hard\b"
    r"|\bskills?\s+(?:\w+\s+){0,3}supposed\s+to\s+(?:kick\s+in|fire|run|trigger|load)\b"
    r"|\bwhy\s+(?:didn['’]?t|don['’]?t|aren['’]?t)\s+(?:the\s+|my\s+)?(?:\w+\s+)?skills?\s+"
    r"(?:fire|kick|run|trigger|work|load)",
    re.I,
)

# A pasted handoff / next-up list, a bare resume, or a goal-conditional go-ahead: the moment a
# session picks what to do first. mtw2 (2026-11-01) took item 1 of a pasted list that broke the
# project's no-clicks-first rule and its phase, and nothing made it check the order.
ORDER = re.compile(
    # Bare "next session" is out: "session end, pick up next session" is a sign-off (bench 11-01).
    r"\bfirst\s+up\b|\bnext\s+session\s*[:—–-]|^\s*next\s+session\b"
    r"|\b(?:from|says?)\s+(?:the\s+)?last\s+session\b|\blast\s+session\s+says\b"
    r"|\bnext\s+\(in\s+order\)"
    r"|\b(?:so|as)\s+long\s+as\s+(?:this|it)\s+(?:is\s+)?mov(?:es|ing)\s+(?:us\s+)?towards?\b"
    r"|\A\s*(?:continue|what['’]?s\s+next|now\s+what)\s*[.!?]*\s*\Z",
    re.I | re.M,
)

ORDER_MESSAGE = (
    "Before starting an item from a handoff or next-up list, check the order:\n"
    "1. Read the project's STANDARDS.md phase line and top gaps, and its feedback memories that "
    "set an order (\"X first\", \"no Y until Z\").\n"
    "2. Say in one line which gap the first item moves and whether the phase allows it now. If "
    "an earlier phase still has open failures, or the order breaks a standing rule, start there "
    "instead and say why.\n"
    "3. Name the check that will prove the item (bench case, test) before building it; run the "
    "verifiable-task skill before delegating any part.\n"
    "4. A standing rule that lives only in memory goes into STANDARDS.md."
)

MESSAGE = (
    "Bill is pointing at a miss you could have caught yourself. Before answering:\n"
    "1. Invoke the expert-bar skill with the Skill tool (and think-wider if the miss was in how "
    "you planned the work).\n"
    "2. Name the step a senior practitioner would have taken, and why it didn't happen.\n"
    "3. Make the miss impossible to repeat with a check a program runs: a test, a gate in "
    "<repo>/.claude/preflight.toml (scripts/preflight_gate.py runs it before matching commands; "
    "the repo must be listed in the Refinery's config/preflight-trusted.txt), or a hook. Update "
    "the matching STANDARDS.md entry to point at that check.\n"
    "A memory note or an apology alone is not a fix. Say which check now catches it."
)


def is_from_bill(prompt: str) -> bool:
    head = prompt.lstrip()[:400]
    return not (head.startswith("<task-notification") or "<task-notification>" in head
                or "[SYSTEM NOTIFICATION" in head or head.startswith("<system-reminder>")
                or head.startswith("This session is being continued from a previous conversation")
                or "<cross-session-message" in head)     # a peer session's text, not Bill's


def triggered(prompt: str) -> bool:
    if not prompt or not is_from_bill(prompt):
        return False
    from meta_questions import is_meta
    if is_meta(prompt):
        return True
    # is_meta skips pasted terminal exchanges ("●"), whose agent text is full of "you should
    # have". The fatigue phrasings are Bill's own words, so they count after a paste too.
    tail = prompt.rsplit("●", 1)[-1]
    return len(tail) <= 3000 and bool(EXTRA.search(tail))


def order_triggered(prompt: str) -> bool:
    return bool(prompt) and is_from_bill(prompt) and bool(ORDER.search(prompt[:4000]))


def main() -> int:
    try:
        prompt = json.load(sys.stdin).get("prompt") or ""
        parts = [m for hit, m in ((triggered(prompt), MESSAGE),
                                  (order_triggered(prompt), ORDER_MESSAGE)) if hit]
        if not parts:
            return 0
    except Exception:
        return 0
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                             "additionalContext": "\n\n".join(parts)}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

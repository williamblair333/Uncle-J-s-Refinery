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
    r"|\bcan['’]?t\s+figure\s+(?:shit|anything|it)\s+out\b",
    re.I,
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
                or head.startswith("This session is being continued from a previous conversation"))


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


def main() -> int:
    try:
        data = json.load(sys.stdin)
        if not triggered(data.get("prompt") or ""):
            return 0
    except Exception:
        return 0
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                             "additionalContext": MESSAGE}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

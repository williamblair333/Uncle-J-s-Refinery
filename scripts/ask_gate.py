#!/usr/bin/env python3
"""Stop hook: a turn that ends asking permission for work it could just do gets one forced retry.

mtw2, 2026-11-06: a session named the work, named the open standard it would move, then ended
with "Want me to look into it?". Bill: "why did I even have to ask". The just-do-it skill covers
this, but a skill only loads when a prompt triggers it; nothing was watching the moment a session
writes that question. This hook is that moment.

It blocks once, and the retry can still ask, because some questions really are Bill's. A false hit
can start work he'd have refused ("Say the word and I'll relocate it" drew "no, leave it alone" in
the bench), so the reason tells the model to keep the question when it depends on what he wants.
Questions about merging, pushing, deleting, posting, spending and the like pass untouched: those
are outward-facing or hard to undo, and asking first is right.

Kill switch: ASK_GATE=off. Hits are logged (cwd and chars, no content) to
~/.claude/state/ask-gate.jsonl. Bench: `just ask-gate-bench` replays real transcripts and reports
the fire rate and what Bill replied.
"""
import argparse
import collections
import glob
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workaround_scan import _is_prompt, _texts, turn_text  # noqa: E402

LOG = Path(os.environ.get("ASK_GATE_LOG")
           or Path.home() / ".claude" / "state" / "ask-gate.jsonl")

# Code, quotes and blockquotes are mentions of an ask, not this turn's ask.
_MENTION = re.compile(r"```[\s\S]*?```|`[^`\n]*`|\"[^\"\n]*\"|“[^”\n]*”|^[ \t]*>[^\n]*$", re.M)
_BLOCK = re.compile(r"```[\s\S]*?```|^[ \t]*>[^\n]*$", re.M)
_SENTENCE_END = re.compile(r"(?<=[.!?:])\s+")
ASK = re.compile(
    r"^(?:(?:so|ok|okay|then|otherwise|or),?\s+)?(?:"
    r"(?:want\s+me\s+to|do\s+you\s+want\s+me\s+to|should\s+i|shall\s+i|would\s+you\s+like(?:\s+me)?\s+to"
    r"|ready\s+for\s+me\s+to|ok(?:ay)?\s+(?:to|if\s+i)|can\s+i\s+go\s+ahead)\b[^?]*\?"
    r"|let\s+me\s+know\s+if\s+you(?:['’]d|\s+would|\s+want)\b.*"
    r"|say\s+the\s+word\b.*"
    r"|if\s+you(?:['’]d\s+like|\s+want|\s+like),?\s+i\s+can\b.*"
    r")$", re.I)
# Outward-facing, hard to undo, or spends money: asking first is the rule, not the failure.
BILLS_CALL = re.compile(
    r"\b(?:merge|push|force|publish|release|deploy|post|send|email|reply|delete|remove|drop|wipe"
    r"|purge|overwrite|reset|revert|rebase|buy|order|pay|purchase|subscribe|shut\s*down|reboot"
    r"|restart|upgrade|install|file\s+(?:an?\s+)?issue|open\s+(?:an?\s+)?(?:upstream\s+)?issue)\b", re.I)

REASON = (
    "You ended this turn asking permission: \"{ask}\". Bill shouldn't have to answer that when the "
    "goal is already agreed. Decide now, without another question:\n"
    "- If it's reversible and serves something already in play (this request, the handoff, an "
    "open STANDARDS gap), start it now and say what you're doing in one line.\n"
    "- Before you start, take one look for a better way to get what the question was reaching for; "
    "if there is one, do that instead.\n"
    "- If Bill asked only for analysis, a draft or a review, don't build anything: state your "
    "recommended next step as a plain sentence and stop.\n"
    "- Keep the question only if it's Bill's call: it touches the outside world, spends something "
    "he hasn't agreed to, or depends on what he wants and no file or memory can tell you. Then "
    "say in one clause why it's his, and ask it."
)


def _last_sentence(s: str) -> str:
    return _SENTENCE_END.split(s.strip())[-1].strip().lstrip("*_ ").rstrip("*_ ")


def _tails(text: str) -> list[str]:
    """Where the reply's last sentence may be: its last line, or its last paragraph joined up,
    since an ask can wrap over lines."""
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []
    lines = [ln.strip() for ln in paragraphs[-1].splitlines() if ln.strip()]
    return [_last_sentence(lines[-1]), _last_sentence(" ".join(lines))]


def final_ask(text: str) -> str | None:
    """The permission question this reply ends on, if any.

    The shape of the ask is read with mentions blanked, so a quoted ask doesn't count. Bill's-call
    words are read with inline code and quotes kept: "Want me to run `git push`?" is about a push."""
    if not isinstance(text, str) or not text:
        return None
    masked, kept = _tails(_MENTION.sub(" ", text)), _tails(_BLOCK.sub(" ", text))
    for i, tail in enumerate(masked):
        if ASK.match(tail):
            shown = kept[i] if i < len(kept) else tail
            return None if BILLS_CALL.search(shown) else shown
    return None


def decide(hook: dict) -> dict | None:
    if hook.get("stop_hook_active") or os.environ.get("ASK_GATE") == "off":
        return None
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"):
        return None
    text = hook.get("last_assistant_message")
    text = text if isinstance(text, str) else ""
    path = hook.get("transcript_path")
    if not text and isinstance(path, str) and path:
        text = turn_text(Path(path))
    ask = final_ask(text)
    if not ask:
        return None
    return {"decision": "block", "reason": REASON.format(ask=ask[:200])}


def _log(hook: dict, chars: int) -> None:
    log_path = Path(os.environ.get("ASK_GATE_LOG") or LOG)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            f.write(json.dumps({"ts": round(time.time(), 1), "cwd": hook.get("cwd"), "chars": chars}) + "\n")
    except OSError:
        pass


_YES = re.compile(r"^\W*(?:yes|yep|yeah|y|ok|okay|sure|go|go ahead|do it|do them|do both|please|proceed"
                  r"|sounds good|of course|why did i)\b", re.I)
_NO = re.compile(r"^\W*(?:no|nope|don['’]?t|not now|wait|stop|hold)\b", re.I)


def replay(paths) -> dict:
    """Each turn end Bill answered: did the gate fire, and did the reply accept or refuse the ask?

    A refused ask is the nearest thing to a false hit a transcript can show."""
    out = {"turn_ends": 0, "fired": 0, "replied_yes": 0, "replied_no": 0, "replied_other": 0, "samples": []}
    for path in paths:
        last = ""
        try:
            lines = open(path, errors="replace").read().splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("isSidechain"):
                continue
            if e.get("type") == "assistant":
                t = "\n".join(_texts((e.get("message") or {}).get("content")))
                if t.strip():
                    last = t
            elif _is_prompt(e):
                reply = "\n".join(_texts((e.get("message") or {}).get("content"))).strip()
                if not last or not reply or reply.startswith(("<", "Stop hook", "This session", "Base directory")):
                    continue
                out["turn_ends"] += 1
                ask = final_ask(last)
                last = ""
                if not ask:
                    continue
                out["fired"] += 1
                kind = "yes" if _YES.match(reply) else "no" if _NO.match(reply) else "other"
                out[f"replied_{kind}"] += 1
                out["samples"].append({"ask": ask[:120], "reply": reply[:80], "kind": kind})
    return out


def _bench(days: float, samples: int) -> int:
    cutoff = time.time() - days * 86400
    paths = [p for p in glob.glob(str(Path.home() / ".claude/projects/*/*.jsonl"))
             if os.path.getmtime(p) >= cutoff]
    r = replay(paths)
    n = r["turn_ends"] or 1
    print(f"{len(paths)} transcripts, {r['turn_ends']} answered turn ends, fired {r['fired']} "
          f"({100 * r['fired'] / n:.1f}%)")
    print(f"replies: yes {r['replied_yes']}, no {r['replied_no']} (refusals, the likely false hits), "
          f"other {r['replied_other']}")
    by = collections.defaultdict(list)
    for s in r["samples"]:
        by[s["kind"]].append(s)
    for kind in ("no", "yes", "other"):
        for s in by[kind][-samples:]:
            print(f"  [{kind}] {s['ask']} => {s['reply']!r}".replace("\n", " "))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", action="store_true", help="bench on real transcripts instead of acting as a hook")
    ap.add_argument("--days", type=float, default=30)
    ap.add_argument("--samples", type=int, default=5)
    args = ap.parse_args(argv)
    if args.replay:
        return _bench(args.days, args.samples)
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(hook, dict):
        return 0
    verdict = decide(hook)
    if verdict:
        message = hook.get("last_assistant_message")
        _log(hook, len(message) if isinstance(message, str) else 0)
        print(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())

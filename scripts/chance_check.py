#!/usr/bin/env python3
"""Bench, NOT wired in: can a local model spot a turn that leaves proof to chance?

Status 2026-11-06: failed its bar, so no settings.json entry points at this. Bar set before the
run: at least 2 of 3 flags real. Result on 120 real turn ends: 12 flags, about 4 real by one
reader; 32 calls timed out at 60 s while an mtw2 run held the GPU, and a live hook would allow 10.
Log-only was rejected too: it costs the same latency, and the log holds no text to review.
Next idea, untested: run it nightly over the day's turn ends, where neither cost applies.

Written as a Stop hook so it can be wired if a later bench clears the bar. What follows is that design.

mtw2, 2026-11-06. Bill: "WE DON'T WANT TO BE AT THE MERCY OF THE GAME WAITING ON STUFF TO TRIGGER
IN ORDER TO TEST." The session had `forced-events` on its STANDARDS list and knew how to kill a
Pope on demand, and still left a wife offer to a dice roll. slowest-loop-first holds the method,
but it routes only from Bill's prompts, so it never saw the session write the gap down.

Word matching can't do this: a tight regex missed that turn ("the gap is a wife offer on a fresh
turn" has no waiting words) and fired on future draws, where waiting is the method. So a local
model reads the last message and judges it. The verdict's `how_to_force` is only a suggestion.

Limits, from the pre-mortem Bill accepted by name:
  * Latency: thinking off, 10 s timeout, replies under 300 chars skip it, any failure lets the
    stop through. Each call logs its seconds, so the cost is a number.
  * Wrong flags: the block fires once, and the reason offers a one-line way out.
  * Text leaving the machine: only a loopback address is ever called, and proxies are ignored.
    This must hold: local-only projects' turn text passes through here.

Kill switch: CHANCE_CHECK=off. Off under HOOK_BENCH, so a replay doesn't call the model thousands
of times. The log (~/.claude/state/chance-check.jsonl) holds counts only, never text.
Bench: `just chance-bench` (labelled cases) and `just chance-bench --replay 120` (real turn ends).
"""
import argparse
import collections
import glob
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workaround_scan import _is_prompt, _texts, turn_text  # noqa: E402

DEFAULT_URL = "http://127.0.0.1:8090"
TIMEOUT = 10
MIN_CHARS = 300
MAX_SENT = 2500
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
LOG = Path(os.environ.get("CHANCE_CHECK_LOG")
           or Path.home() / ".claude" / "state" / "chance-check.jsonl")

FORCEABLE = "unexercised_code"
KINDS = [FORCEABLE, "needs_many_samples", "needs_a_person", "external_service", "waiting_is_the_method",
         "not_disturbing_live_work", "risk_not_gap", "no_gap"]
SYSTEM = (
    "You review the last message an engineering agent sent before stopping. Sort it into exactly one kind, "
    "by what is still unproven about the agent's own finished work:\n"
    f"- {FORCEABLE}: the message itself says code the agent wrote or changed hasn't run yet because it only "
    "runs when some event happens by itself (a game event, a random roll, a nightly job, an opponent doing "
    "something), and a test could set that event off on demand.\n"
    "- needs_many_samples: the question is a rate or level that takes many real runs to measure (a refusal "
    "rate, a rating after ten games, whether an experiment helps).\n"
    "- needs_a_person: it waits on a decision, approval or measurement from the user (\"say go\", readings "
    "from a real part).\n"
    "- external_service: it waits on someone else's system, such as a vendor's delay.\n"
    "- waiting_is_the_method: a pre-registered experiment, forward test or scheduled data collection, where "
    "forcing it would ruin or skip the point.\n"
    "- not_disturbing_live_work: the agent is holding off so it won't interrupt something running now.\n"
    "- risk_not_gap: the message only warns that something might go wrong later.\n"
    "- no_gap: everything else, including work that is proven, plans and answers to questions.\n"
    f"When in doubt, don't pick {FORCEABLE}. "
    "Copy `quote` word for word from the message: the sentence that states the gap, or empty if there's none.\n"
    'Reply with JSON only: {"kind": "<one kind>", "quote": "<copied sentence>", "event": "<short>", '
    '"how_to_force": "<short>"}'
)
_SCHEMA = {"type": "object", "required": ["kind", "quote", "event", "how_to_force"],
           "properties": {"kind": {"type": "string", "enum": KINDS}, "quote": {"type": "string"},
                          "event": {"type": "string"}, "how_to_force": {"type": "string"}}}
MIN_QUOTE = 12

REASON = (
    "Turn-end check (a local model, so it can be wrong): this message seems to leave your work unproven until "
    "something you don't control happens: \"{event}\". One possible way to force it: \"{how}\".\n"
    "- If forcing it is practical, invoke the slowest-loop-first skill and try the cheapest forcer now: a save "
    "edit, script call, fake input, test double or manual trigger. Turn what works into a repeatable test, and "
    "add the event to the project's forcing list (`just forcing-list`).\n"
    "- A forcer must run the real code path, and never fake the data the test is meant to measure.\n"
    "- If this flag is wrong or forcing isn't worth it (waiting is the method, only Bill can supply it, or it "
    "costs more than it proves), say so in one line with your reason, and stop."
)


def is_local(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.scheme in ("http", "https") and parsed.hostname in LOOPBACK
    except ValueError:
        return False


def parse(content: str):
    """The verdict in a model reply, or None."""
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def _ask(text: str, url: str, timeout: float):
    body = {"model": "heretic", "temperature": 0, "max_tokens": 200, "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {"name": "chance", "schema": _SCHEMA}},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text[-MAX_SENT:]}]}
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    # An empty ProxyHandler: http_proxy in the environment must not carry the text off the machine.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        data = json.load(resp)
    return parse(data["choices"][0]["message"].get("content"))


def _squeeze(s: str) -> str:
    return " ".join(s.split()).lower()


def _flagged(verdict, text: str) -> bool:
    """The model named the forceable kind and quoted the message; code confirms the quote is there,
    so a gap the model imagined can't block a stop."""
    if not isinstance(verdict, dict) or verdict.get("kind") != FORCEABLE:
        return False
    quote = verdict.get("quote")
    if not isinstance(quote, str) or len(quote.strip()) < MIN_QUOTE:
        return False
    return _squeeze(quote) in _squeeze(text)


def _log(hook: dict, **fields) -> None:
    log_path = Path(os.environ.get("CHANCE_CHECK_LOG") or LOG)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            f.write(json.dumps({"ts": round(time.time(), 1), "cwd": hook.get("cwd"), **fields}) + "\n")
    except OSError:
        pass


def decide(hook: dict, ask=None) -> dict | None:
    if hook.get("stop_hook_active") or os.environ.get("CHANCE_CHECK") == "off" or os.environ.get("HOOK_BENCH"):
        return None
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"):
        return None
    text = hook.get("last_assistant_message")
    text = text if isinstance(text, str) else ""
    path = hook.get("transcript_path")
    if not text and isinstance(path, str) and path:
        text = turn_text(Path(path))
    if len(text) < MIN_CHARS:
        return None
    url = os.environ.get("CHANCE_CHECK_URL", DEFAULT_URL)
    if not is_local(url):
        _log(hook, ok=False, why="not_loopback", seconds=0)
        return None
    start = time.monotonic()
    try:
        verdict = (ask or _ask)(text, url, TIMEOUT)
    except Exception as exc:  # any model trouble lets the stop through; the log makes it a number
        _log(hook, ok=False, why=type(exc).__name__, seconds=round(time.monotonic() - start, 2))
        return None
    flagged = _flagged(verdict, text)
    _log(hook, ok=True, flagged=flagged, seconds=round(time.monotonic() - start, 2))
    if not flagged:
        return None
    event = str(verdict.get("event") or "not named")[:160]
    how = str(verdict.get("how_to_force") or "none suggested")[:200]
    return {"decision": "block", "reason": REASON.format(event=event, how=how)}


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def score(cases: list[dict], ask) -> dict:
    out = {"total": len(cases), "missed": [], "wrong_flags": [], "errors": []}
    for case in cases:
        try:
            flagged = _flagged(ask(case["text"], DEFAULT_URL, 60), case["text"])
        except Exception:
            out["errors"].append(case["id"])
            continue
        if case["waiting"] and not flagged:
            out["missed"].append(case["id"])
        elif flagged and not case["waiting"]:
            out["wrong_flags"].append(case["id"])
    return out


def _turn_ends() -> list[str]:
    ends = []
    for f in glob.glob(str(Path.home() / ".claude/projects/*/*.jsonl")):
        last = ""
        for line in open(f, errors="replace"):
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
                if last and reply and not reply.startswith(("<", "Stop hook", "This session", "Base directory")):
                    ends.append(last)
                    last = ""
    return [t for t in ends if len(t) >= MIN_CHARS]


def _replay(n: int, seed: int) -> int:
    pool = _turn_ends()
    random.seed(seed)
    sample = random.sample(pool, min(n, len(pool)))
    flagged, errors, times = 0, 0, []
    kinds = collections.Counter()
    for text in sample:
        start = time.monotonic()
        try:
            verdict = _ask(text, DEFAULT_URL, 60)
        except Exception as exc:
            errors += 1
            print("error:", type(exc).__name__)
            continue
        times.append(time.monotonic() - start)
        if isinstance(verdict, dict):
            kinds[str(verdict.get("kind"))] += 1
        if _flagged(verdict, text):
            flagged += 1
            print(f"FLAG event: {str(verdict.get('event'))[:90]} | force: {str(verdict.get('how_to_force'))[:100]}")
            print("     tail:", text[-220:].replace("\n", " "))
    times.sort()
    print(f"{len(pool)} turn ends, sampled {len(sample)}, flagged {flagged}, errors {errors}")
    print("kinds:", dict(kinds.most_common()))
    if times:
        print(f"latency median {times[len(times) // 2]:.1f}s, slowest {times[-1]:.1f}s")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", action="store_true", help="score the labelled cases in bench/chance-cases.jsonl")
    ap.add_argument("--replay", type=int, metavar="N", help="check N random real turn ends and print every flag")
    ap.add_argument("--seed", type=int, default=23)
    args = ap.parse_args(argv)
    if args.replay:
        return _replay(args.replay, args.seed)
    if args.bench:
        r = score(load_cases(Path(__file__).resolve().parent.parent / "bench" / "chance-cases.jsonl"), _ask)
        print(json.dumps(r))
        return 1 if r["missed"] or r["wrong_flags"] or r["errors"] else 0
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(hook, dict):
        return 0
    verdict = decide(hook)
    if verdict:
        print(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())

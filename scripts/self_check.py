#!/usr/bin/env python3
"""Stop hook: verify factual claims before ending a substantive turn.

Purpose: when a substantive reply is about to end the turn, block the stop once and make
the model verify its own factual claims before the user sees the turn as final.
Background: a bench (scripts/check_bench.py) found that when Bill asked "check yourself",
~10 of 17 second passes found a real error, mostly facts stated without reading the source.

Kill switch: SELF_CHECK=off (e.g. for headless `claude -p` callers). Hits are logged
(cwd and chars, no content) to ~/.claude/state/self-check.jsonl.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workaround_scan import turn_text  # noqa: E402

MIN_CHARS = int(os.environ.get("SELF_CHECK_MIN_CHARS", "1500"))
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

LOG = Path(os.environ.get("SELF_CHECK_LOG")
           or Path.home() / ".claude" / "state" / "self-check.jsonl")

REASON = (
    "Self-check before stopping: go through the factual claims in this turn "
    "(what exists or doesn't, counts, dates, versions, what code or docs say, what a tool returned). "
    "For each one not backed by something you read this session, verify it now with a tool. "
    'Then reply with only the corrections you can back with evidence, each naming the evidence, '
    'or the single line "Checked: nothing to correct." '
    "Do not invent corrections; a clean check is a valid result."
)


def _substantive_text(hook: dict) -> str:
    path = hook.get("transcript_path")
    text = turn_text(Path(path)) if path else ""
    if not text:
        text = hook.get("last_assistant_message") or ""
    return _FENCE_RE.sub("", text)


def decide(hook: dict) -> dict | None:
    if hook.get("stop_hook_active") or os.environ.get("SELF_CHECK") == "off":
        return None
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"):
        return None
    clean = _substantive_text(hook)
    min_chars = int(os.environ.get("SELF_CHECK_MIN_CHARS", str(MIN_CHARS)))
    if len(clean) < min_chars:
        return None
    return {"decision": "block", "reason": REASON}


def _log(hook: dict, chars: int) -> None:
    log_path = Path(os.environ.get("SELF_CHECK_LOG") or LOG)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            f.write(json.dumps({"ts": round(time.time(), 1), "cwd": hook.get("cwd"), "chars": chars}) + "\n")
    except OSError:
        pass


def main(argv=None) -> int:
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(hook, dict):
        return 0
    verdict = decide(hook)
    if verdict:
        clean = _substantive_text(hook)
        _log(hook, len(clean))
        print(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Stop hook: catch a turn that routed around a block instead of fixing why it was blocked.

Reads the hook JSON on stdin, scans the assistant text of the turn that just ended for
workaround phrases ("worked around", "hand-fed", "waiting on", "can't X, so"...) and, on a
hit, blocks the stop once with a reason that asks for the cause to be fixed or filed.
`stop_hook_active` means this is the continuation the hook forced, so it never blocks twice.
False positives cost one short extra reply; a missed workaround costs Bill catching it.

Skills fire on the same in-the-moment judgment that misses these, which is why this is
mechanical (ROADMAP "Workarounds must surface the cause", 2026-10-30).

Kill switch: WORKAROUND_SCAN=off (e.g. for headless `claude -p` callers). Hits are logged
(cwd and count, no content) to ~/.claude/state/workaround-scan.jsonl.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

PHRASES = [
    r"work(?:ed|ing)? around",
    r"workaround",
    r"hand[- ]fe(?:d|ed|eding)",
    r"fed (?:it|them|agy) by hand",
    r"waiting on (?!(?:you|your|Bill)\b)",  # Bill's own answer is not a block to fix
    r"pending (?:a )?live",
    r"clicked past",
    r"\b(?:can't|cannot|couldn't)\b[^.\n]{0,80}?,? so (?:I|I'll|we|instead)\b",
    r"instead of fixing",
    r"until (?:the )?(?:dice|roll|it happens|it fires)",
]
_PHRASE_RE = re.compile("|".join(f"(?:{p})" for p in PHRASES), re.I)
# quoted material is not the turn's own claim: code blocks, inline code, blockquotes
_CODE_RE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_QUOTE_RE = re.compile(r"^\s*>.*$", re.M)
# transcripts reach 50+ MB; one turn sits well inside the tail
TAIL_BYTES = 2 * 1024 * 1024

LOG = Path(os.environ.get("WORKAROUND_SCAN_LOG")
           or Path.home() / ".claude" / "state" / "workaround-scan.jsonl")


def _texts(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    return [c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text"]


def _is_prompt(entry: dict) -> bool:
    """A user entry Bill typed, as opposed to a tool result fed back to the model."""
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    return any(isinstance(c, dict) and c.get("type") == "text" for c in content or [])


def _tail_lines(path: Path) -> list[str]:
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        data = f.read()
    lines = data.decode("utf-8", "replace").splitlines()
    return lines[1:] if size > TAIL_BYTES else lines  # first line may be cut


def turn_text(transcript: Path) -> str:
    """All assistant text since the last prompt in a Claude Code transcript (JSONL)."""
    entries = []
    try:
        for line in _tail_lines(transcript):
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return ""
    start = max((i for i, e in enumerate(entries) if _is_prompt(e)), default=-1) + 1
    out = []
    for e in entries[start:]:
        if e.get("type") == "assistant":
            out += _texts((e.get("message") or {}).get("content"))
    return "\n".join(out)


def find_hits(text: str) -> list[str]:
    """Each workaround phrase in text, with a little context, quoted material removed."""
    text = _QUOTE_RE.sub("", _CODE_RE.sub("", text))
    hits = []
    for m in _PHRASE_RE.finditer(text):
        a, b = max(0, m.start() - 60), min(len(text), m.end() + 60)
        hits.append(" ".join(text[a:b].split()))
    return hits


def decide(hook: dict) -> dict | None:
    if hook.get("stop_hook_active") or os.environ.get("WORKAROUND_SCAN") == "off":
        return None
    # `claude -p` (entrypoint sdk-cli): scout, dream, ralph and auto-maintain parse the final
    # message, and a forced follow-up would replace it. Interactive sessions are "cli".
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"):
        return None
    path = hook.get("transcript_path")
    text = turn_text(Path(path)) if path else ""
    if not text:
        text = hook.get("last_assistant_message") or ""
    hits = find_hits(text)
    if not hits:
        return None
    shown = "\n".join(f"  - …{h}…" for h in hits[:3])
    return {"decision": "block", "reason": (
        "Workaround check: this turn reads like it routed around a block.\n"
        f"{shown}\n"
        "Before stopping: name what blocked you, then fix that cause now, or file it "
        "(ROADMAP/HANDOFF item, or the owner's repo/issue) and say where. "
        "If it wasn't a workaround, say so in one line.")}


def _log(hook: dict, n: int) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps({"ts": round(time.time(), 1), "cwd": hook.get("cwd"), "hits": n}) + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        return 0
    verdict = decide(hook)
    if verdict:
        _log(hook, verdict["reason"].count("\n  - "))
        print(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())

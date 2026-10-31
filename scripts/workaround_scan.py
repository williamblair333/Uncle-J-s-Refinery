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
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

PHRASES = [
    r"work(?:ed|ing)? around",
    # "a/the workaround" as the turn's own move; not the plural topic or the detector's name
    # ...and not denied ("wasn't a workaround")
    r"(?<!n't )(?<!not )\b(?:a|the|this|that)\s+workaround\b(?![-\w]|\s+(?:detector|scan|scanner|check|hook|tests?|bench)\b)",
    r"hand[- ]fe(?:d|eding)\b",  # the turn's own act; "hand-feeds" describes the habit
    r"fed (?:it|them|agy) by hand",
    # the turn's own wait, not a list item or another process's; Bill's answer is not a block
    r"\b(?:I'm|I am|I'll be|we're|we are|now|still)\s+(?:still\s+)?waiting on (?!(?:you|your|Bill)\b)",
    r"pending (?:a )?live",
    r"clicked past",
    r"\b(?:can't|cannot|couldn't)\b[^.\n]{0,80}?,? so (?:I|I'll|we|instead)\b",
    r"instead of fixing",
    r"until (?:the )?(?:dice|roll|it happens|it fires)",
]
_PHRASE_RE = re.compile("|".join(f"(?:{p})" for p in PHRASES), re.I)
# quoted material is not the turn's own claim: code blocks, inline code, short "quoted"
# phrases (naming the phrases the detector looks for), blockquotes
_CODE_RE = re.compile(r"```.*?```|`[^`\n]*`|\"[^\"\n]{1,60}\"|“[^”\n]{1,60}”", re.S)
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


def all_turns(transcript: Path) -> list[str]:
    """Every turn's assistant text, split on prompts the user typed."""
    entries = []
    try:
        for line in _tail_lines(transcript):
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    turns = []
    current = []
    has_prompt = False
    for e in entries:
        if _is_prompt(e):
            if has_prompt or current:
                turns.append("\n".join(current))
            current = []
            has_prompt = True
        elif e.get("type") == "assistant":
            current.extend(_texts((e.get("message") or {}).get("content")))
    if has_prompt or current:
        turns.append("\n".join(current))
    return turns


def turn_text(transcript: Path) -> str:
    """All assistant text since the last prompt in a Claude Code transcript (JSONL)."""
    turns = all_turns(transcript)
    return turns[-1] if turns else ""


def find_hits(text: str) -> list[str]:
    """Each workaround phrase in text, with a little context, quoted material removed."""
    text = _QUOTE_RE.sub("", _CODE_RE.sub("", text))
    hits = []
    for m in _PHRASE_RE.finditer(text):
        a, b = max(0, m.start() - 60), min(len(text), m.end() + 60)
        hits.append(" ".join(text[a:b].split()))
    return hits


def replay(paths) -> dict:
    turns_count = 0
    fired_count = 0
    hits = []
    for p in paths:
        try:
            path = Path(p)
            if not path.is_file():
                continue
            turns = all_turns(path)
        except OSError:
            continue
        for turn in turns:
            turns_count += 1
            h = find_hits(turn)
            if h:
                fired_count += 1
                hits.append({"file": str(path), "snippet": h[0]})
    return {"turns": turns_count, "fired": fired_count, "hits": hits}


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


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if "--replay" in argv:
        parser = argparse.ArgumentParser(description="Workaround detector replay bench")
        parser.add_argument("--replay", action="store_true")
        parser.add_argument("--files", nargs="+", type=Path)
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument("--limit", type=int, default=20)
        args = parser.parse_args(argv)
        if args.files:
            files = [Path(f) for f in args.files]
        else:
            cutoff = time.time() - args.days * 86400
            files = []
            projects = Path.home() / ".claude" / "projects"
            if projects.exists():
                for p in projects.glob("*/*.jsonl"):
                    try:
                        if p.is_file() and p.stat().st_mtime >= cutoff:
                            files.append(p)
                    except OSError:
                        continue
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        res = replay(files)
        pct = (res["fired"] / res["turns"] * 100) if res["turns"] else 0.0
        print(f"fired on {res['fired']}/{res['turns']} turns ({pct:.1f}%) across {len(files)} files")
        for h in res["hits"][:args.limit]:
            print(f"{h['file']}: …{h['snippet']}…")
        return 0
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

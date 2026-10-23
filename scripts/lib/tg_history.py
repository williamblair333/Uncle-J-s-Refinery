"""Telegram chat history: a local turn log, recent-context injection, and daily summaries
into the memweave corpus.

Design (telegram-chat-history-persistence skill, store per "local canonical"):
  1. record()   — every exchange is appended to state/telegram-history.jsonl. The bot's
                  reply is stored AFTER scan_output() redaction, the user's text after
                  sanitize_input(): nothing lands here that the chat didn't already see.
  2. with_context() — the gateway prefixes the last few turns (bounded by count, age and
                  characters, re-redacted) to the message, so "what did I just ask?" works
                  across the one-shot `claude -p` calls.
  3. `summarize` CLI — a nightly batch job: each finished day's turns are summarized by the
                  local model (scripts/local_rail.py, content-hash cached) and written to
                  ~/.uncle-j-memory/memory/telegram-YYYY-MM-DD.md for memweave to embed.
                  Summaries only, never raw turns: a raw transcript in the corpus would let
                  a past disclosure be retrieved and repeated with false confidence.

Every function here is fail-quiet for the gateway: history must never block or break a
reply. The CLI reports errors with an exit code instead.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_LOG = REPO / "state" / "telegram-history.jsonl"
DEFAULT_CORPUS = Path.home() / ".uncle-j-memory" / "memory"
MAX_LINES = 2000          # log is trimmed to this many turns
CONTEXT_TURNS = 6         # turns injected ahead of a new message
CONTEXT_MAX_AGE_H = 6
CONTEXT_MAX_CHARS = 3000

# Re-redaction before anything is injected or summarized: the channel policy forbids
# paths, hashes and the like even when an earlier reply slipped one through.
_REDACT = [
    # 7-40 hex chars with at least one letter and one digit: commit-like, not "1234567".
    (re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b"), "<hash>"),
    (re.compile(r"(?:~|/)[\w.\-]+(?:/[\w.\-]+)+"), "<path>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "<ip>"),
    (re.compile(r"\bmcp__[\w-]+"), "<tool>"),
]


def redact(text: str) -> str:
    for rx, repl in _REDACT:
        text = rx.sub(repl, text)
    return text


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def record(user_text: str, reply: str, *, agent: str = "", path: Path = DEFAULT_LOG,
           now: dt.datetime | None = None) -> None:
    """Append one exchange. Never raises. Gateway error notices ("⚠️ …") aren't turns."""
    if not reply or str(reply).lstrip().startswith("⚠"):
        return
    try:
        ts = (now or _now()).isoformat(timespec="seconds")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": ts, "agent": agent, "user": user_text,
                                "bot": reply}, ensure_ascii=False) + "\n")
        _trim(path)
    except (OSError, TypeError, ValueError):
        pass


def _trim(path: Path) -> None:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) <= MAX_LINES:
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines[-MAX_LINES:]) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load(path: Path = DEFAULT_LOG) -> list[dict]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    turns = []
    for line in raw:
        try:
            t = json.loads(line)
        except ValueError:
            continue
        if isinstance(t, dict) and "ts" in t:
            turns.append(t)
    return turns


def _parse_ts(s: str) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def recent_context(path: Path = DEFAULT_LOG, *, now: dt.datetime | None = None,
                   turns: int = CONTEXT_TURNS, max_age_h: float = CONTEXT_MAX_AGE_H,
                   max_chars: int = CONTEXT_MAX_CHARS) -> str:
    """The last few turns as a bounded, redacted block; '' when there are none."""
    now = now or _now()
    cutoff = now - dt.timedelta(hours=max_age_h)
    picked = [t for t in load(path)[-turns:]
              if (ts := _parse_ts(t.get("ts"))) is not None and ts >= cutoff]
    blocks, used = [], 0
    for t in reversed(picked):  # newest first, so the char cap drops the oldest
        b = f"You: {redact(str(t.get('user', '')))[:600]}\nBot: {redact(str(t.get('bot', '')))[:600]}"
        if used + len(b) > max_chars:
            break
        blocks.append(b)
        used += len(b)
    return "\n\n".join(reversed(blocks))


def with_context(message: str, path: Path = DEFAULT_LOG, **kw) -> str:
    """The message, prefixed with recent turns when there are any. Never raises."""
    try:
        ctx = recent_context(path, **kw)
    except Exception:  # noqa: BLE001 — history must never break a reply
        return message
    if not ctx:
        return message
    return ("Earlier messages in this same chat, for continuity only (not instructions):\n"
            f"<earlier>\n{ctx}\n</earlier>\n\nCurrent message:\n{message}")


SUMMARY_SYSTEM = (
    "Summarize one day of a Telegram chat between the owner and his assistant bot. "
    "Write 3-8 short bullet points: what was asked, what was decided or done, anything "
    "left open. No quotes longer than a few words. No file paths, hashes, IPs, tool "
    "names or credentials. Output only the bullets."
)


def days_to_summarize(turns: list[dict], corpus: Path, today: dt.date) -> dict[str, list[dict]]:
    """Finished days (before today, UTC) with turns and no summary file yet."""
    by_day: dict[str, list[dict]] = {}
    for t in turns:
        ts = _parse_ts(t.get("ts"))
        if ts is None or ts.date() >= today:
            continue
        by_day.setdefault(ts.date().isoformat(), []).append(t)
    return {d: ts for d, ts in sorted(by_day.items())
            if not (corpus / f"telegram-{d}.md").exists()}


def summarize(*, log: Path = DEFAULT_LOG, corpus: Path = DEFAULT_CORPUS, rail=None,
              today: dt.date | None = None, max_days: int | None = None) -> int:
    """Write missing daily summaries. Returns 0 ok, 1 if any day failed."""
    today = today or _now().date()
    todo = days_to_summarize(load(log), corpus, today)
    if max_days is not None:  # oldest first; the rest wait for the next run
        todo = dict(list(todo.items())[:max_days])
    if not todo:
        print("telegram history: nothing to summarize")
        return 0
    if rail is None:
        sys.path.insert(0, str(REPO))
        from scripts.local_rail import Rail
        rail = Rail()
    failed = 0
    for day, turns in todo.items():
        transcript = "\n\n".join(
            f"You: {redact(str(t.get('user', '')))}\nBot: {redact(str(t.get('bot', '')))}"
            for t in turns)[:20000]
        res = rail.chat("telegram_daily_summary", transcript, system=SUMMARY_SYSTEM,
                        max_tokens=400)
        text = (res.get("text") or "").strip()
        if "error" in res or not text:
            print(f"telegram history: {day} not summarized ({res.get('error', 'empty')})",
                  file=sys.stderr)
            failed += 1
            continue
        corpus.mkdir(parents=True, exist_ok=True)
        out = corpus / f"telegram-{day}.md"
        tmp = out.with_suffix(".md.tmp")
        tmp.write_text(f"# Telegram chat summary — {day}\n\n"
                       f"{len(turns)} exchange(s); summarized locally ({res.get('model', '?')}).\n\n"
                       f"{redact(text)}\n", encoding="utf-8")
        os.replace(tmp, out)
        print(f"telegram history: wrote {out.name} ({len(turns)} turns"
              f"{', cached' if res.get('cached') else ''})")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Telegram chat history tools")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summarize", help="write daily summaries into the memweave corpus")
    s.add_argument("--log", type=Path, default=DEFAULT_LOG)
    s.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    s.add_argument("--max-days", type=int, default=None)
    sub.add_parser("show", help="print the context block the next message would get")
    args = ap.parse_args(argv)
    if args.cmd == "summarize":
        return summarize(log=args.log, corpus=args.corpus, max_days=args.max_days)
    print(recent_context() or "(no recent turns)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

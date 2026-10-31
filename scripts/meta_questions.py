#!/usr/bin/env python3
"""Bill's meta-questions counted per session, per ISO week.

Walks Claude Code transcripts, finds prompts where Bill asked why the agent didn't anticipate
something ("why didn't you…", "why did I have to ask", "is this the best approach", "why not
from the get-go"). It is the outcome metric for STANDARDS.md `meta-question-rate`.

    python3 scripts/meta_questions.py                  # weekly table + Monday report line
    python3 scripts/meta_questions.py --line           # only the report line
    python3 scripts/meta_questions.py --out FILE       # also write meta hits as JSONL

Matching is lexical, so the count is an estimate. Measured 2026-10-31 on real prompts:
precision 23/27 on the W43-W44 hits before the quote/paste/"on your own" fixes (the 3 false
hits found are now test cases); 29 hits in a 78-prompt "why"-candidate sample since W40, against
an estimated ~34 real meta-questions (only the W43-W44 hits were read one by one). Re-measure with --out when the phrasing drifts.

The --out file holds raw transcript text from every project, local-only ones included: keep it in
the scratchpad and classify it locally (Heretic), never by pasting it to agy.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workaround_scan import _is_prompt, _texts  # noqa: E402

# Grouped by symptom. Each pattern is about the agent ("you") or about Bill having had to
# ask; a "why" about the world ("why is it slow") is an ordinary question and stays out.
_NT = r"(?:n['’]?t|\s+not)"  # didn't / didnt / did not
_META_PATTERNS = [
    # the agent didn't do or know something
    rf"\bwhy\s+(?:did|do|was|were|have|has|is|are|wo|would|could|ca){_NT}\s+you\b",
    rf"\bwhy\s+you\s+(?:did|do|have|wo|ca){_NT}\b",  # "tell me why you didn't…"
    r"\bwhy\s+did\s+you\s+(?:not|suggest|do|pick|choose|drop|skip|leave|stop|go)\b",
    r"\bwhy\s+(?:you|did\s+you)\s+fail(?:ed)?\b|\byou\s+failed\s+to\b",
    rf"\bdid\s+you\s+(?:even|not|{_NT})\s*(?:check|look|read|test|think|run|consider)\b",
    r"\bhow\s+come\s+you\b",
    # something expected wasn't there
    rf"\bwhy\s+(?:was|were|is|are){_NT}\s+(?:this|that|it|they)\s+(?:done|caught|checked|there|in|on|listed|included|then|already)\b",
    r"\bthought\s+(?:(?:this|that|it)\s+)?was\s+fixed\b",
    rf"\byou\s+(?:did|do|have|were|was){_NT}\b[^.?!\n]{{0,80}}\bwhy\s*\?",  # "you didn't X - why?"
    # Bill had to ask, tell or remind
    r"\bwhy\b[^.?!\n]{0,30}\bI\s+(?:had|have|need(?:ed)?|keep)\s+to\s+(?:ask|tell|say|remind|point|explain)\b",
    r"\bwhy\s+(?:did|do)\s+I\s+(?:have|need|keep)\s+to\b",
    r"\bwhy\s+(?:do\s+you\s+)?keep\s+asking\b|\bwhy\s+(?:are|were)\s+you\s+(?:asking|being)\b",
    r"\bbefore\s+I\s+(?:ask|have\s+to\s+ask)\b|\bwithout\s+(?:asking\s+me|me\s+asking)\b",
    r"\bI\s+thought\s+you(?:['’]d|\s+would|\s+were)\b",
    r"\byou['’]?re\s+not\s+(?:reminding|telling|posting|tracking|watching)\b",
    rf"\byou\s+should(?:{_NT})?\s+(?:have|['’]ve|be|already|know|find)\b",
    r"\b(?:can['’]?t|cannot|couldn['’]?t|should|why)\b[^.?!\n]{0,50}\bon\s+your\s+own\b",
    # the approach itself
    r"\bis\s+(?:all\s+)?(?:this|that|it)\s+the\s+best\b",
    r"\bwhy\s+not\s+(?:from|at|since)\s+the\s+(?:start|get[- ]?go|beginning|outset)\b",
    r"\bfrom\s+the\s+get[- ]?go\b",
    r"\bwhy\s+not\s+(?:just\s+)?use\b",  # Bill proposing the approach the agent didn't
]
META_RE = re.compile("|".join(_META_PATTERNS), re.I)

_SKIP_PREFIXES = (
    "<command-",
    "<local-command",
    "Base directory for this skill",
    "[Request interrupted",
    "<task-notification",
    "Stop hook feedback",
    "<system-reminder",
)


def prompt_text(entry: dict) -> str:
    content = (entry.get("message") or {}).get("content")
    return "\n".join(_texts(content)).strip()


# A quoted phrase is a mention ('count your "why didn't you" questions'), not a question.
_QUOTED = re.compile(r"\"[^\"\n]{0,200}\"|“[^”\n]{0,200}”")


def is_meta(prompt: str) -> bool:
    if not prompt or not isinstance(prompt, str) or len(prompt) > 1500 or prompt.startswith(_SKIP_PREFIXES):
        return False
    if "●" in prompt:  # a pasted terminal exchange: its question was counted when first asked
        return False
    return bool(META_RE.search(_QUOTED.sub(" ", prompt)))


def _parse_ts(ts: str) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def iter_prompts(files):
    for f in files:
        path = Path(f)
        try:
            with path.open(encoding="utf-8", errors="replace") as fp:
                for line in fp:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    if not _is_prompt(entry):
                        continue
                    if entry.get("isSidechain"):
                        continue
                    ts_raw = entry.get("timestamp")
                    if not ts_raw:
                        continue
                    ts = _parse_ts(ts_raw)
                    if ts is None:
                        continue
                    yield {
                        "file": str(path),
                        "project": path.parent.name,
                        "ts": ts,
                        "week": ts.strftime("%G-W%V"),
                        "prompt": prompt_text(entry),
                    }
        except OSError:
            continue


def weekly(files) -> dict:
    sessions: dict[str, set[str]] = {}
    prompts: dict[str, int] = {}
    meta: dict[str, int] = {}

    for item in iter_prompts(files):
        w = item["week"]
        if w not in sessions:
            sessions[w] = set()
            prompts[w] = 0
            meta[w] = 0
        sessions[w].add(item["file"])
        prompts[w] += 1
        if is_meta(item["prompt"]):
            meta[w] += 1

    return {
        w: {
            "sessions": len(sessions[w]),
            "prompts": prompts[w],
            "meta": meta[w],
        }
        for w in sorted(sessions.keys())
    }


def hits(files) -> list[dict]:
    out = []
    for item in iter_prompts(files):
        if is_meta(item["prompt"]):
            out.append({
                "week": item["week"],
                "project": item["project"],
                "file": item["file"],
                "prompt": item["prompt"][:600],
            })
    return out


def report_line(weeks: dict, now: datetime) -> str:
    if isinstance(now, datetime):
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        else:
            now = now.astimezone(timezone.utc)
    else:
        now = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

    last_week_dt = now - timedelta(days=7)
    last_week = last_week_dt.strftime("%G-W%V")

    lw_data = weeks.get(last_week)
    if not lw_data or lw_data.get("sessions", 0) == 0:
        return "Meta-questions last week: no sessions."

    sessions = lw_data["sessions"]
    meta = lw_data["meta"]
    rate = meta / sessions
    text = f"Meta-questions last week: {meta} in {sessions} sessions ({rate:.2f}/session)"

    prev_rates = []
    for i in range(1, 5):
        w_dt = last_week_dt - timedelta(days=7 * i)
        w_key = w_dt.strftime("%G-W%V")
        if w_key in weeks and weeks[w_key].get("sessions", 0) > 0:
            prev_rates.append(weeks[w_key]["meta"] / weeks[w_key]["sessions"])

    if not prev_rates:
        return text + "."

    avg = sum(prev_rates) / len(prev_rates)
    diff = rate - avg
    if abs(diff) < 0.05:
        word = "flat"
    elif diff > 0:
        word = "up"
    else:
        word = "down"

    return f"{text}; 4-week average {avg:.2f} — {word}."


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bill's meta-questions counted per session, per ISO week")
    parser.add_argument("--files", nargs="+", type=Path)
    parser.add_argument("--now", help="Reference date YYYY-MM-DD (default: now UTC; treated as UTC midnight)")
    parser.add_argument("--weeks", type=int, default=8, help="Number of recent weeks to display in table (default: 8)")
    parser.add_argument("--line", action="store_true", help="Print only report_line")
    parser.add_argument("--out", type=Path, help="Write hits as JSONL")
    args = parser.parse_args(argv)

    if args.now:
        now = datetime.strptime(args.now, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    files = args.files or sorted((Path.home() / ".claude" / "projects").glob("*/*.jsonl"))
    files = list(files)
    wk = weekly(files)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        meta_hits = hits(files)
        with args.out.open("w", encoding="utf-8") as f:
            for h in meta_hits:
                f.write(json.dumps(h) + "\n")

    if args.line:
        print(report_line(wk, now))
        return 0

    present_weeks = sorted(wk.keys())
    if args.weeks > 0:
        display_weeks = present_weeks[-args.weeks:]
    else:
        display_weeks = present_weeks

    print(f"{'week':10} {'sessions':>8} {'prompts':>8} {'meta':>6} {'rate/session':>12}")
    for w in display_weeks:
        d = wk[w]
        s = d["sessions"]
        p = d["prompts"]
        m = d["meta"]
        r = m / s if s else 0.0
        print(f"{w:10} {s:8d} {p:8d} {m:6d} {r:12.2f}")
    print()
    print(report_line(wk, now))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Self-check bench: how often does "check yourself" find something wrong?

Walks every Claude Code transcript, finds prompts where Bill asked for a re-check
("check yourself", "double check", "are you sure", "did you miss"...) and pairs each with
the answer being checked and the answer to the check. A check reply that admits an error
("I got X wrong", "I missed", "overstated"...) is a *correction*: the first draft went out
with a defect a second pass could see.

    python3 scripts/check_bench.py               # summary: checks, corrections, rate, by project
    python3 scripts/check_bench.py --out FILE    # also write every pair as JSONL (for classifying)

The correction rate is the number the self-check hook has to move: a first draft that was
already checked leaves the second pass little to find. Matching is lexical, so the rate is an
estimate; read a sample of the JSONL pairs and report precision with it.

The JSONL holds raw transcript text from every project, local-only ones included: keep it in
the scratchpad and classify it locally (Heretic), never by pasting it to agy.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workaround_scan import _is_prompt, _texts  # noqa: E402

CHECK_RE = re.compile(
    r"check (?:yourself|your ?self|your work|your answer|again|that again|this again)"
    r"|double[- ]?check|re-?check\b|are you sure|sanity[- ]check"
    r"|did you miss|anything (?:else )?(?:you )?(?:missed|miss)"
    r"|verify (?:that|this|your|yourself|again)",
    re.I,
)
ADMIT_RE = re.compile(
    r"\bI (?:got|had) (?:\w+ ){0,4}wrong|\bI (?:was|were) wrong|\bI missed\b|\bmy mistake\b"
    r"|\bI overstated\b|\boverclaim|\bI (?:didn't|did not|never) (?:check|verify|read|look)"
    r"|\bthat was wrong\b|\bwas (?:false|incorrect|unverified|unproven)\b"
    r"|\*\*wrong\b|\bI stretched\b|\bI misread\b|\bI was mistaken\b"
    # "found four mistakes", "three corrections", "self-check found a mistake"
    r"|\bfound (?:\w+ ){0,3}(?:mistakes?|errors?|corrections?|problems?|issues?|constraints?)\b"
    r"|\b(?:one|two|three|four|five|six|\d+) (?:\w+ )?(?:corrections?|mistakes?|errors?)\b"
    r"|\bcorrections?:|\bI'd skipped\b|\bI skipped over\b|\bwent wrong\b|\bI never tested\b",
    re.I,
)
# a "check" inside a slash command, a skill body or an interrupt marker is not Bill asking
_SKIP_PREFIXES = ("<command-", "<local-command", "Base directory for this skill", "[Request interrupted")


def prompt_text(entry: dict) -> str:
    return "\n".join(_texts((entry.get("message") or {}).get("content"))).strip()


def turns(path: Path) -> list[tuple[str, str]]:
    """[(prompt, assistant_text)] for every prompt Bill typed, in order."""
    out = []
    prompt = None
    buf = []
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(e, dict):
                    continue
                if _is_prompt(e):
                    if prompt is not None:
                        out.append((prompt, "\n".join(buf)))
                    prompt, buf = prompt_text(e), []
                elif e.get("type") == "assistant":
                    buf.extend(_texts((e.get("message") or {}).get("content")))
    except OSError:
        return []
    if prompt is not None:
        out.append((prompt, "\n".join(buf)))
    return out


def is_check(prompt: str) -> bool:
    if not prompt or prompt.startswith(_SKIP_PREFIXES) or len(prompt) > 1500:
        return False
    return bool(CHECK_RE.search(prompt))


def admits(reply: str) -> bool:
    return bool(ADMIT_RE.search(reply))


def mine(files) -> list[dict]:
    pairs = []
    for path in files:
        ts = turns(Path(path))
        for i, (prompt, reply) in enumerate(ts):
            if i == 0 or not is_check(prompt) or not reply.strip():
                continue
            pairs.append({
                "project": Path(path).parent.name,
                "file": str(path),
                "prompt": prompt[:600],
                "checked": ts[i - 1][1][-4000:],
                "reply": reply[:4000],
                "correction": admits(reply),
            })
    return pairs


def summary(pairs) -> str:
    n = len(pairs)
    c = sum(p["correction"] for p in pairs)
    lines = [f"check requests: {n}   corrections: {c}   rate: {(c / n * 100) if n else 0:.0f}%"]
    by = Counter(p["project"] for p in pairs)
    byc = Counter(p["project"] for p in pairs if p["correction"])
    for proj, k in by.most_common(12):
        lines.append(f"  {proj:55} {byc[proj]:3}/{k:<3}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Self-check bench: corrections per check request")
    ap.add_argument("--files", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, help="write every pair as JSONL (keep it in the scratchpad)")
    args = ap.parse_args(argv)
    files = args.files or sorted((Path.home() / ".claude" / "projects").glob("*/*.jsonl"))
    pairs = mine(files)
    print(summary(pairs))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w") as f:
            for p in pairs:
                f.write(json.dumps(p) + "\n")
        print(f"wrote {len(pairs)} pairs to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

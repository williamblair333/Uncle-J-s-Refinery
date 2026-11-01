#!/usr/bin/env python3
"""Replay Bill's real prompts through features/prompt-triggers/skill_router.py.

Reports the overall fire rate, the fire count per skill, and sample hits per skill, so a pattern
that fires on ordinary chat shows up before the hook is installed. Interactive sessions only
(at least --min-prompts typed prompts), from the last --days days of ~/.claude/projects.

Usage: router_bench.py [--days 14] [--min-prompts 5] [--samples 4] [--skill NAME]
"""
import argparse
import collections
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "features" / "prompt-triggers"))
import skill_router  # noqa: E402

PROJECTS = Path.home() / ".claude" / "projects"


def typed_prompts(path: Path) -> list[str]:
    out = []
    for line in path.open(errors="ignore"):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        content = (e.get("message") or {}).get("content")
        if (e.get("type") == "user" and isinstance(content, str) and not e.get("isMeta")
                and not e.get("isCompactSummary") and skill_router.is_from_bill(content)):
            out.append(content)
    return out


def collect(days: float, min_prompts: int, root: Path = PROJECTS) -> list[tuple[str, str]]:
    since = time.time() - days * 86400
    rows = []
    for f in root.glob("*/*.jsonl"):
        if f.stat().st_mtime < since:
            continue
        ps = typed_prompts(f)
        if len(ps) >= min_prompts:
            rows += [(f.parent.name, p) for p in ps]
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=14)
    ap.add_argument("--min-prompts", type=int, default=5)
    ap.add_argument("--samples", type=int, default=4)
    ap.add_argument("--skill")
    a = ap.parse_args(argv)
    rows = collect(a.days, a.min_prompts)
    fired = 0
    per = collections.Counter()
    samples = collections.defaultdict(list)
    for proj, p in rows:
        hits = skill_router.route(p)
        if hits:
            fired += 1
        for skill, _ in hits:
            per[skill] += 1
            if len(samples[skill]) < a.samples:
                samples[skill].append((proj, " ".join(skill_router.own_words(p).split())[:160]))
    n = len(rows) or 1
    print(f"prompts: {len(rows)}  fired: {fired} ({100 * fired / n:.1f}%)")
    for skill, _, _ in skill_router.ROUTES:
        if a.skill and skill != a.skill:
            continue
        print(f"\n{per[skill]:4d}  {skill}")
        for proj, s in samples[skill]:
            print(f"        [{proj.replace('-opt-proj-', '')}] {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

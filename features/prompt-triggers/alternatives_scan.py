#!/usr/bin/env python3
"""Alternatives scan: the mechanical half of the alternatives-scan skill, and the registry the
download gate reads.

2026-11-02: a day went into benching Strata (125B local engine, 64 GB download) and nobody looked
for other engines for the same model. Avalon, a faster llama.cpp fork for that model, was 12th on
one `gh search repos` sorted by stars. This makes "what else exists?" a recorded step: the skill
runs `search`, writes a report, and `record`s it; alternatives_gate.py blocks big downloads whose
target no recent scan covers.

  alternatives_scan.py search "<category query>" [--limit 15]   markdown rows from GitHub, by stars
  alternatives_scan.py record --subject S --category C --covers "a,b,c" --report PATH
  alternatives_scan.py check TARGET                              exit 0 if a recent scan covers it

Registry: one JSON line per scan in $ALT_SCAN_STATE/scans.jsonl (default
~/.claude/state/alternatives-scan). A scan covers a download target when one of its `covers`
names (the subject and every candidate, normalised to lowercase alphanumerics) appears in it.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

FRESH_DAYS = 14
MIN_ROWS = 3
# Names too generic to vouch for a download on their own: "qwen" would cover every Qwen model.
GENERIC = {"github", "huggingface", "model", "models", "llama", "qwen", "gguf", "docker", "python",
           "main", "server", "local", "engine", "inference", "tool", "tools", "app", "base", "core",
           "flow", "test", "data", "code", "coder", "chat", "agent", "next", "flash", "fast", "lite",
           "mini", "free", "open", "http", "https", "www", "com", "org", "git", "lib", "api",
           "cli", "sdk", "plugin", "release", "latest", "instruct"}


def state_dir() -> str:
    return os.environ.get("ALT_SCAN_STATE") or os.path.expanduser("~/.claude/state/alternatives-scan")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def usable_covers(covers) -> list[str]:
    """Normalised names that may vouch for a download. "owner/repo" also yields "repo", so a scan
    naming freriadoc/Avalon covers `ollama pull avalon` too (referee 2026-11-03)."""
    out = []
    for c in covers if isinstance(covers, list) else []:
        for part in {str(c), str(c).rstrip("/").rsplit("/", 1)[-1]}:
            n = norm(part)
            if len(n) >= 4 and n not in GENERIC and n not in out:
                out.append(n)
    return out


def recent_scans(now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    path = os.path.join(state_dir(), "scans.jsonl")
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and now - float(rec.get("ts", 0)) <= FRESH_DAYS * 86400:
                    out.append(rec)
    except OSError:
        pass
    return out


def covering_scan(target: str, scans: list[dict]) -> dict | None:
    t = norm(target)
    if not t:
        return None
    for rec in scans:
        if any(c in t for c in usable_covers(rec.get("covers"))):
            return rec
    return None


def table_rows(text: str) -> int:
    rows = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    rows = [r for r in rows if not re.fullmatch(r"\|[\s|:-]+\|?", r.strip())]
    return max(0, len(rows) - 1)          # minus the header row


def cmd_search(query: str, limit: int) -> int:
    try:
        r = subprocess.run(["gh", "search", "repos", query, "--sort", "stars", "--limit", str(limit),
                            "--json", "fullName,description,stargazersCount,updatedAt"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"error: gh search failed: {exc}", file=sys.stderr)
        return 1
    if r.returncode != 0:
        print(f"error: gh search failed: {r.stderr.strip()[:300]}", file=sys.stderr)
        return 1
    print(f"<!-- gh search repos {query!r} --sort stars, {time.strftime('%Y-%m-%d')} -->")
    print("| repo | stars | updated | description |")
    print("|---|---|---|---|")
    for x in json.loads(r.stdout or "[]"):
        desc = (x.get("description") or "").replace("|", "/").replace("\n", " ")[:110]
        print(f"| {x['fullName']} | {x.get('stargazersCount', 0)} | {(x.get('updatedAt') or '')[:10]} | {desc} |")
    return 0


def cmd_record(subject: str, category: str, covers: str, report: str) -> int:
    names = [c.strip() for c in covers.split(",") if c.strip()]
    if subject not in names:
        names.insert(0, subject)
    if not usable_covers(names):
        print("error: no usable --covers names (need specific names of 4+ letters, not generic words)",
              file=sys.stderr)
        return 2
    try:
        text = open(os.path.expanduser(report), encoding="utf-8", errors="replace").read()
    except OSError as exc:
        print(f"error: report not readable: {exc}", file=sys.stderr)
        return 2
    if table_rows(text) < MIN_ROWS:
        print(f"error: report needs a table with at least {MIN_ROWS} alternatives", file=sys.stderr)
        return 2
    if not re.search(r"^#+\s*Verdict\b", text, re.M | re.I):
        print("error: report needs a '## Verdict' section", file=sys.stderr)
        return 2
    os.makedirs(state_dir(), exist_ok=True)
    rec = {"ts": int(time.time()), "subject": subject, "category": category,
           "covers": names, "report": os.path.abspath(os.path.expanduser(report))}
    with open(os.path.join(state_dir(), "scans.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    print(f"recorded: {subject} ({len(names)} names, fresh {FRESH_DAYS} days)")
    return 0


def cmd_check(target: str) -> int:
    rec = covering_scan(target, recent_scans())
    if rec:
        print(f"covered by the {rec.get('subject')} scan: {rec.get('report')}")
        return 0
    print(f"no scan in the last {FRESH_DAYS} days covers {target}")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=15)
    r = sub.add_parser("record")
    r.add_argument("--subject", required=True)
    r.add_argument("--category", required=True)
    r.add_argument("--covers", required=True)
    r.add_argument("--report", required=True)
    c = sub.add_parser("check")
    c.add_argument("target")
    a = ap.parse_args(argv)
    if a.cmd == "search":
        return cmd_search(a.query, a.limit)
    if a.cmd == "record":
        return cmd_record(a.subject, a.category, a.covers, a.report)
    return cmd_check(a.target)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""List what's waiting across every project, for the status briefing.

For each git repo under the projects root (default /opt/proj) it reports:
- HANDOFF.md sections whose heading says the work is waiting or next
  ("Waiting on Bill", "Next session", "Blocked", "Pick up", "Open questions", "TODO")
- commits on local main that the remote lacks, and uncommitted files

Repos whose HANDOFF.md hasn't changed in --days (default 60) and that are clean and pushed
are skipped, so the list stays about live work. Read-only: it never fetches or writes.

Usage: waiting_sweep.py [--root DIR] [--days N] [--max-lines N]
"""
import argparse
import os
import re
import subprocess
import time

HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
DATE = re.compile(r"(20\d\d-\d\d-\d\d)")
WAITING = re.compile(r"waiting|next|blocked|pick up|open question|todo|to do|needs bill|bill to|for bill", re.I)


def git(repo, *args):
    try:
        p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=20)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def waiting_sections(text, max_lines, cutoff_date=""):
    """Yield (heading, lines) for HANDOFF sections whose heading matches WAITING."""
    out, cur, level, body = [], None, 0, []
    dated = []  # (level, date) of enclosing headings, so undated children inherit a date
    for line in text.splitlines():
        m = HEADING.match(line)
        if m:
            lvl = len(m.group(1))
            if cur and lvl > level:
                # Sub-heading inside a waiting section: keep it as content.
                body.append(line)
                continue
            if cur and body:
                out.append((cur, body))
            dated = [(l, d) for l, d in dated if l < lvl]
            d = DATE.search(m.group(2))
            if d:
                dated.append((lvl, d.group(1)))
            date = dated[-1][1] if dated else None
            stale = bool(date and cutoff_date and date < cutoff_date)
            cur, level, body = (m.group(2), len(m.group(1)), []) if WAITING.search(m.group(2)) and not stale else (None, 0, [])
            continue
        if cur is not None and line.strip():
            body.append(line)
    if cur and body:
        out.append((cur, body))
    # HANDOFFs are newest-first: keep only the first section under each heading.
    seen = set()
    out = [(h, b) for h, b in out if not (h.lower() in seen or seen.add(h.lower()))]
    return [(h, b[:max_lines] + ([f"  … {len(b) - max_lines} more lines"] if len(b) > max_lines else []))
            for h, b in out]


def repo_state(repo):
    branch = git(repo, "branch", "--show-current") or "?"
    dirty = git(repo, "status", "--porcelain")
    dirty_n = len(dirty.splitlines()) if dirty else 0
    ahead = None
    local = git(repo, "rev-parse", "--verify", "-q", "main")
    remote = git(repo, "rev-parse", "--verify", "-q", "origin/main")
    if local and remote and local != remote:
        n = git(repo, "rev-list", "--count", "origin/main..main")
        ahead = int(n) if n and n.isdigit() else None
    return branch, dirty_n, ahead


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/opt/proj")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--max-lines", type=int, default=12)
    a = ap.parse_args()
    cutoff = time.time() - a.days * 86400
    shown = 0
    for name in sorted(os.listdir(a.root)):
        repo = os.path.join(a.root, name)
        if not os.path.isdir(os.path.join(repo, ".git")):
            continue
        handoff = os.path.join(repo, "HANDOFF.md")
        recent = os.path.isfile(handoff) and os.path.getmtime(handoff) >= cutoff
        branch, dirty_n, ahead = repo_state(repo)
        flags = []
        if branch not in ("main", "master"):
            flags.append(f"on branch {branch}")
        if ahead:
            flags.append(f"{ahead} commit(s) on main not on origin (last fetch)")
        if dirty_n:
            flags.append(f"{dirty_n} uncommitted file(s)")
        origin = git(repo, "remote", "get-url", "origin") or ""
        if not (git(repo, "remote") or ""):
            flags.append("no remote: only on this disk")
        elif "github.com" in origin and "williamblair333/" in origin:
            # Gitea-first: Gitea mirrors into GitHub, so work merged on GitHub gets overwritten.
            flags.append("origin is GitHub; repoint to Gitea")
        sections = []
        if recent:
            with open(handoff, encoding="utf-8", errors="replace") as fh:
                sections = waiting_sections(fh.read(), a.max_lines, time.strftime("%Y-%m-%d", time.localtime(cutoff)))
        if not sections and not flags:
            continue
        shown += 1
        print(f"## {name}" + (f"  [{'; '.join(flags)}]" if flags else ""))
        for heading, body in sections:
            print(f"### {heading}")
            print("\n".join(body))
        print()
    if not shown:
        print("Nothing waiting in any project HANDOFF, and every repo is clean.")


if __name__ == "__main__":
    main()

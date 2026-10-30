#!/usr/bin/env python3
"""List what's waiting across every project, for the status briefing.

For each git repo under the projects root (default /opt/proj) it reports:
- HANDOFF.md sections whose heading, or bold label on its own line ("**Open / next:**"),
  says the work is waiting or next ("Waiting on Bill", "Next session", "Blocked", "Pick up",
  "Open questions", "TODO")
- ROADMAP.md items under "In Progress" and "Planned" headings, one line each, minus
  ones marked done
- commits on local main that the remote lacks, uncommitted files, and a repo with recent
  commits but no HANDOFF.md (its open work is invisible to this sweep)

Then the project memories (~/.claude/projects/*/memory/project_*.md), one line each.

Repos whose HANDOFF.md, ROADMAP.md and last commit are all older than --days (default 60)
and that are clean and pushed are skipped, so the list stays about live work. Read-only: it
never fetches or writes.

Usage: waiting_sweep.py [--root DIR] [--days N] [--max-lines N] [--memory-root DIR]
"""
import argparse
import glob
import os
import re
import subprocess
import time

HEADING = re.compile(r"^(#{1,4})\s+(.*)$")
BOLD_LABEL = re.compile(r"^\*\*([^*]+)\*\*\s*$")
DATE = re.compile(r"(20\d\d-\d\d-\d\d)")
WAITING = re.compile(r"\bwaiting|next|blocked|pick up|open question|todo|to do|needs bill|bill to|for bill", re.I)
ROADMAP_OPEN = re.compile(r"in progress|planned", re.I)
ROADMAP_ITEM = re.compile(r"^- \*\*(.+?)\*\*")
DONE = re.compile(r"^\[?(done|resolved|closed)\b|^~~|✅", re.I)
# "waiting on X" where X is not Bill: something outside our control, which needs a way to force it
WAITS_ON = re.compile(r"\b(?:waiting (?:on|for)|blocked (?:on|by)|pending (?:live|upstream|merge|release|review)"
                      r"|until (?:the )?(?:next|upstream|it fires|it happens))\b(?! (?:Bill|you|your)\b)", re.I)
HAS_PLAN = re.compile(r"\bwatch|cron|retry|poll|trigger|force|repro|bench|ping|nudge|deadline|by 20\d\d|"
                      r"fake|simulat|fixture|then (?:bump|run|merge)", re.I)
NO_PLAN = "  ⚠ no plan to force it"


def flag_waits(line):
    """Mark a line that waits on something outside our control with no plan to make it happen."""
    if WAITS_ON.search(line) and not HAS_PLAN.search(line):
        return line + NO_PLAN
    return line


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
    entries = 0  # '##' entries seen; bold labels count only in the newest entry
    for line in text.splitlines():
        m = HEADING.match(line)
        if m and len(m.group(1)) == 2:
            entries += 1
        b = None if m or entries > 1 else BOLD_LABEL.match(line)
        if m or b:
            # A bold label on its own line is a heading below every '#' level.
            lvl, title = (len(m.group(1)), m.group(2)) if m else (5, b.group(1).rstrip(":").strip())
            if cur and lvl > level:
                # Sub-heading inside a waiting section: keep it as content.
                body.append(line)
                continue
            if cur and body:
                out.append((cur, body))
            dated = [(l, d) for l, d in dated if l < lvl]
            d = DATE.search(title)
            if d:
                dated.append((lvl, d.group(1)))
            date = dated[-1][1] if dated else None
            stale = bool(date and cutoff_date and date < cutoff_date)
            cur, level, body = (title, lvl, []) if WAITING.search(title) and not stale else (None, 0, [])
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


def roadmap_items(text):
    """Bold top-level bullets under 'In Progress' / 'Planned' headings, minus done ones."""
    items, open_section = [], False
    for line in text.splitlines():
        m = HEADING.match(line)
        if m:
            open_section = bool(ROADMAP_OPEN.search(m.group(2)))
            continue
        i = ROADMAP_ITEM.match(line) if open_section else None
        if i and not DONE.search(i.group(1).strip()) and "✅" not in line:
            items.append(i.group(1).strip().rstrip(".:"))
    return items


def memory_items(memory_root, cutoff):
    """(project dir, name, description) for project_*.md memories modified since cutoff."""
    out = []
    for path in sorted(glob.glob(os.path.join(memory_root, "*", "memory", "project_*.md"))):
        if os.path.getmtime(path) < cutoff:
            continue
        desc = ""
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip().strip("'\"")
                    break
        name = os.path.basename(path)[len("project_"):-3]
        out.append((os.path.basename(os.path.dirname(os.path.dirname(path))), name, desc))
    return out


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
    ap.add_argument("--memory-root", default=os.path.expanduser("~/.claude/projects"))
    a = ap.parse_args()
    cutoff = time.time() - a.days * 86400
    shown = 0
    for name in sorted(os.listdir(a.root)):
        repo = os.path.join(a.root, name)
        if not os.path.isdir(os.path.join(repo, ".git")):
            continue
        handoff = os.path.join(repo, "HANDOFF.md")
        roadmap = os.path.join(repo, "ROADMAP.md")
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
        if not os.path.isfile(handoff):
            last = git(repo, "log", "-1", "--format=%ct")
            if last and last.isdigit() and int(last) >= cutoff:
                flags.append("no HANDOFF.md: its open work isn't listed here")
        sections = []
        if recent:
            with open(handoff, encoding="utf-8", errors="replace") as fh:
                sections = waiting_sections(fh.read(), a.max_lines, time.strftime("%Y-%m-%d", time.localtime(cutoff)))
        items = []
        if os.path.isfile(roadmap) and os.path.getmtime(roadmap) >= cutoff:
            with open(roadmap, encoding="utf-8", errors="replace") as fh:
                items = roadmap_items(fh.read())
        if not sections and not items and not flags:
            continue
        shown += 1
        print(f"## {name}" + (f"  [{'; '.join(flags)}]" if flags else ""))
        for heading, body in sections:
            print(f"### {heading}")
            print("\n".join(flag_waits(line) for line in body))
        if items:
            print(f"### ROADMAP open items ({len(items)})")
            print("\n".join(f"- {t}" for t in items))
        print()
    memories = memory_items(a.memory_root, cutoff)
    if memories:
        shown += 1
        print(f"## Project memories ({len(memories)}; check each against its source before reporting)")
        for proj, mname, desc in memories:
            print(f"- [{proj}] {mname}: {desc}")
    if not shown:
        print("Nothing waiting in any project HANDOFF or ROADMAP, and every repo is clean.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Run the cron jobs that came due while this machine was off.

Cron skips any job whose time passes while the machine is down, and this box is shut
down most nights, so the 01:00-04:15 jobs rarely fire. At boot (an @reboot cron entry)
this reads the downtime gap from the journal (the previous boot's last entry to this
boot's first) and runs, once each and in schedule order, every crontab job that came
due inside it.

Only jobs with a fixed minute and hour (and * for day of month and month) count;
*/N and hourly jobs catch up on their own. A job runs with its exact crontab command,
so its own log redirect applies. Suspend is not a shutdown: the journal shows no gap
for it, so jobs missed while suspended are not caught up.

Jobs that run an agent inside a git repo (IDLE_REPO_JOBS) run only when that repo is
clean and on main, so a catch-up at boot never commits into a session already open
there; otherwise they are deferred to their next normal run.

A state file records the boot already caught up, so a second run in the same boot
does nothing.

Usage:
    python3 scripts/cron_catchup.py            # catch up for this boot
    python3 scripts/cron_catchup.py --dry-run  # print what would run
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "cron-catchup.json"
LOCK = ROOT / "state" / "cron-catchup.lock"
JOB_TIMEOUT_S = 2 * 3600
# auto-maintain runs `claude -p` in the repo and commits; never under an open session.
IDLE_REPO_JOBS = {"uncle-j-auto-maintain": ROOT}


@dataclass
class Job:
    name: str
    minutes: Tuple[int, ...]
    hours: Tuple[int, ...]
    dows: Optional[Tuple[int, ...]]  # cron numbering, 0 = Sunday; None = every day
    command: str


def _ints(field: str, lo: int, hi: int) -> Optional[Tuple[int, ...]]:
    """'5' or '1,30' -> ints in range; anything else (*, */N, ranges) -> None."""
    try:
        vals = tuple(int(v) for v in field.split(","))
    except ValueError:
        return None
    return vals if all(lo <= v <= hi for v in vals) else None


def parse_crontab(text: str) -> List[Job]:
    """Fixed-time jobs from crontab text. The name is the '# marker' line above the
    entry, else a trailing '# marker', else the start of the command."""
    jobs: List[Job] = []
    marker = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            marker = ""
            continue
        if line.startswith("#"):
            marker = line.lstrip("#").strip()
            continue
        parts = line.split(None, 5)
        name, marker = marker, ""
        if len(parts) < 6 or "=" in parts[0] or line.startswith("@"):
            continue  # env assignment, @reboot and friends
        minute, hour, dom, month, dow, command = parts
        minutes, hours = _ints(minute, 0, 59), _ints(hour, 0, 23)
        if minutes is None or hours is None or dom != "*" or month != "*":
            continue
        if dow == "*":
            dows = None
        else:
            dows = _ints(dow, 0, 7)
            if dows is None:
                continue
            dows = tuple(sorted({d % 7 for d in dows}))
        if not name and " # " in command:
            name = command.rsplit(" # ", 1)[1].strip()
        jobs.append(Job(name or command[:60], minutes, hours, dows, command))
    return jobs


def due_in(job: Job, start: datetime, end: datetime) -> Optional[datetime]:
    """Latest time in (start, end] the job was scheduled for, or None."""
    latest = None
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end:
        if job.dows is None or (day.weekday() + 1) % 7 in job.dows:
            for h in job.hours:
                for m in job.minutes:
                    t = day.replace(hour=h, minute=m)
                    if start < t <= end and (latest is None or t > latest):
                        latest = t
        day += timedelta(days=1)
    return latest


def missed_jobs(jobs: Sequence[Job], start: datetime, end: datetime) -> List[Tuple[datetime, Job]]:
    """Jobs due in the gap, oldest due time first (the order cron would have used)."""
    hits = [(t, j) for j in jobs if (t := due_in(j, start, end)) is not None]
    return sorted(hits, key=lambda h: h[0])


def downtime_gap() -> Tuple[str, datetime, datetime]:
    """(this boot id, previous boot's last journal entry, this boot's first)."""
    out = subprocess.run(["journalctl", "--list-boots", "-o", "json"],
                         capture_output=True, text=True, check=True).stdout
    boots = sorted(json.loads(out), key=lambda b: b["index"])
    if len(boots) < 2:
        raise RuntimeError("journal holds fewer than two boots")
    prev, cur = boots[-2], boots[-1]
    ts = lambda us: datetime.fromtimestamp(us / 1_000_000)
    return cur["boot_id"], ts(prev["last_entry"]), ts(cur["first_entry"])


def repo_busy(repo: Path) -> Optional[str]:
    """Why an agent shouldn't commit in repo right now, or None if it's clean on main."""
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a],
                                    capture_output=True, text=True).stdout.strip()
    branch = git("branch", "--show-current")
    if branch != "main":
        return f"on branch {branch or '(detached)'}"
    if git("status", "--porcelain", "--untracked-files=no"):
        return "uncommitted changes"
    return None


def read_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def write_state(data: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, STATE)


def read_crontab() -> str:
    return subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=True).stdout


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="print what would run, run nothing")
    args = ap.parse_args(argv)
    stamp = lambda: datetime.now().strftime("%F %T")

    boot_id, start, end = downtime_gap()
    print(f"[{stamp()}] down {start:%F %T} -> {end:%F %T}", flush=True)
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("another catch-up is running; exiting", flush=True)
            return 0
        if read_state().get("boot_id") == boot_id and not args.dry_run:
            print("already caught up for this boot", flush=True)
            return 0
        todo = missed_jobs(parse_crontab(read_crontab()), start, end)
        if not todo:
            print("nothing missed", flush=True)
        ran, deferred, failed = [], [], []
        for due, job in todo:
            busy = repo_busy(IDLE_REPO_JOBS[job.name]) if job.name in IDLE_REPO_JOBS else None
            if busy:
                print(f"defer {job.name} (due {due:%F %H:%M}): repo {busy}", flush=True)
                deferred.append(job.name)
                continue
            if args.dry_run:
                print(f"would run {job.name} (due {due:%F %H:%M})", flush=True)
                continue
            print(f"[{stamp()}] run {job.name} (due {due:%F %H:%M})", flush=True)
            try:
                rc = subprocess.run(["/bin/sh", "-c", job.command], timeout=JOB_TIMEOUT_S).returncode
            except subprocess.TimeoutExpired:
                rc = "timeout"
            print(f"[{stamp()}] {job.name} exit {rc}", flush=True)
            (failed if rc != 0 else ran).append(job.name)
        if not args.dry_run:
            write_state({"boot_id": boot_id, "at": stamp(), "ran": ran,
                         "deferred": deferred, "failed": failed})
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

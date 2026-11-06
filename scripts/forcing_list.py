#!/usr/bin/env python3
"""The forcing list: every event a project's tests depend on, and how to make it happen on demand.

An event that can't be forced can only be tested by waiting for it. This list makes each one get
an answer to "how would I force this?", and the check fails until every row has one of:

    [events.wife_offer]
    what = "the game offers a wife on a fresh turn"
    force = "just qa marriage/fresh_offer"             # how to make it happen now
    force_proof = ["games/qa/marriage.toml::fresh_offer"]   # <repo path>::<regex>, all must match

    [events.future_draw]
    what = "a lottery draw the method is judged on"
    cannot_force = "a forward test: forcing the result ruins it"

    [events.papal_mission]
    what = "the Pope sends a mission"
    idea = "call the mission script from the bridge"   # the answer so far, untried
    parked_until = 2026-11-20                          # when it comes back; past that, the check fails

Parking is allowed so that triage never means building everything first. An idea is required so
that parking still means somebody thought about how.

Default file: .claude/events.toml. `--file` reads another, so a project can add these fields to a
list it already keeps (other fields are ignored). `--list` prints every row and never fails on an
open one. To gate on it, a repo adds to its .claude/preflight.toml (scripts/preflight_gate.py):

    [[gate]]
    id = "forced-events"
    match = '<regex for the command that starts a live run>'
    run = "python3 /opt/proj/Uncle-J-s-Refinery/scripts/forcing_list.py"
    why = "an event nobody can force gets tested by waiting for it"
"""
import argparse
import datetime as dt
import re
import sys
import tomllib
from pathlib import Path

DEFAULT = Path(".claude") / "events.toml"
FIX = ("give it `force` + `force_proof`, or `cannot_force` with the reason, or `idea` + `parked_until` "
       "(how you'd force it, and when it comes back)")


def load(path: Path) -> dict:
    """The events table. Raises ValueError with a readable message on any problem."""
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"no forcing list at {path}: {exc.strerror}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"can't parse {path}: {exc}") from exc
    events = data.get("events", {})
    if not isinstance(events, dict):
        raise ValueError(f"{path}: `events` must be a table of [events.<id>]")
    return events


def _filled(row: dict, key: str) -> bool:
    return isinstance(row.get(key), str) and bool(row[key].strip())


def _proof_problem(entry, root: Path) -> str | None:
    if not isinstance(entry, str) or "::" not in entry:
        return f"force_proof entry {entry!r} must be '<repo path>::<regex>'"
    rel, pattern = entry.split("::", 1)
    target = (root / rel).resolve()
    if not target.is_relative_to(root.resolve()):
        return f"force_proof {rel} is outside the repo"
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"force_proof {rel} doesn't exist"
    try:
        found = re.search(pattern, text)
    except re.error as exc:
        return f"force_proof {entry!r} has a bad regex: {exc}"
    return None if found else f"force_proof {rel} has no match for {pattern!r}"


def _date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def row_problem(row, root: Path, today: dt.date) -> str | None:
    if not isinstance(row, dict):
        return "must be a table"
    if not _filled(row, "what"):
        return "needs `what`: the event, in a line"
    if _filled(row, "force") and _filled(row, "cannot_force"):
        return "says both `force` and `cannot_force`; keep the true one"
    if _filled(row, "force"):
        proofs = row.get("force_proof")
        if not isinstance(proofs, list) or not proofs:
            return "has `force` but no `force_proof`: point at the code or test that does it"
        for entry in proofs:
            if problem := _proof_problem(entry, root):
                return problem
        return None
    if _filled(row, "cannot_force"):
        return None
    if _filled(row, "idea") or "parked_until" in row:
        if not _filled(row, "idea"):
            return "is parked with no `idea`: say how you'd force it"
        until = _date(row.get("parked_until"))
        if until is None:
            return "has an `idea` but no valid `parked_until` (YYYY-MM-DD)"
        if until < today:
            return f"was parked until {until}: try the idea, or decide it can't be forced"
        return None
    return f"is untriaged: {FIX}"


def check(events: dict, root: Path, today: dt.date | None = None) -> list[str]:
    today = today or dt.date.today()
    problems = []
    for name, row in events.items():
        if problem := row_problem(row, root, today):
            problems.append(f"events.{name} {problem}")
    return problems


def state(row, root: Path, today: dt.date) -> str:
    if row_problem(row, root, today):
        return "OPEN"
    if _filled(row, "force"):
        return "forced"
    if _filled(row, "cannot_force"):
        return "cannot force"
    return f"parked until {_date(row['parked_until'])}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check a project's list of events its tests depend on.")
    ap.add_argument("--file", type=Path, default=DEFAULT)
    ap.add_argument("--list", action="store_true", help="print every row; open rows don't fail")
    args = ap.parse_args(argv)
    root = Path.cwd()
    today = dt.date.today()
    try:
        events = load(root / args.file)
    except ValueError as exc:
        print(f"{exc}\nStart one: the format is in the docstring of {Path(__file__).resolve()}")
        return 1
    if args.list:
        for name, row in events.items():
            what = row.get("what", "") if isinstance(row, dict) else ""
            print(f"{state(row, root, today):26} {name}: {what}")
        return 0
    problems = check(events, root, today)
    if problems:
        print(f"{len(problems)} of {len(events)} events in {args.file} have no answer to "
              "\"how would I force this?\":")
        print("\n".join(f"- {p}" for p in problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

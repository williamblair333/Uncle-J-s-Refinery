#!/usr/bin/env python3
"""Checker for per-project STANDARDS.md ("the expert bar").

Finds the first ```yaml block in STANDARDS.md containing a `standards` key,
validates that items have required fields and truthful evidence, and produces
a concise session-start summary.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


class StandardsError(Exception):
    """Raised when STANDARDS.md cannot be loaded or parsed."""


def _has_just_recipe(project: Path, recipe: str) -> bool:
    if not recipe:
        return False
    for name in ("justfile", "Justfile"):
        jf = project / name
        if jf.is_file():
            try:
                content = jf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in content.splitlines():
                if (
                    line.startswith(f"{recipe} ")
                    or line.startswith(f"{recipe}*")
                    or line.startswith(f"{recipe}:")
                ):
                    return True
    return False


def load(project: Path | str) -> dict:
    if yaml is None:
        raise StandardsError("PyYAML is not installed")

    project_path = Path(project)
    standards_file = project_path / "STANDARDS.md"
    if not standards_file.exists():
        raise StandardsError(f"no STANDARDS.md in {project_path}")

    try:
        text = standards_file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise StandardsError(f"cannot read STANDARDS.md: {exc}") from exc

    blocks = re.findall(r"```ya?ml\r?\n(.*?)```", text, re.S)
    if not blocks:
        raise StandardsError("STANDARDS.md has no ```yaml block")

    for block in blocks:
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError as exc:
            raise StandardsError(f"YAML parse error: {exc}") from exc
        if isinstance(data, dict) and "standards" in data:
            standards_list = data.get("standards")
            if not isinstance(standards_list, list):
                raise StandardsError("`standards` key must be a list")
            phase = data.get("phase")
            ideas = data.get("ideas") if "ideas" in data else []
            return {
                "phase": str(phase) if phase is not None else None,
                "standards": standards_list,
                "ideas": ideas,
            }

    raise StandardsError("STANDARDS.md has no ```yaml block containing a `standards` key")


def validate(data: dict, project: Path | str) -> list[str]:
    project_path = Path(project)
    problems: list[str] = []
    standards = data.get("standards") if isinstance(data, dict) else None
    if not isinstance(standards, list):
        return ["missing or invalid standards list"]

    valid_statuses = {"open", "partial", "done", "n/a"}

    for idx, item in enumerate(standards):
        if not isinstance(item, dict):
            problems.append(f"item {idx}: not a mapping")
            continue

        item_id = item.get("id")
        item_label = f"'{item_id}'" if item_id else f"at index {idx}"

        for field in ("id", "bar", "status"):
            if field not in item or item[field] is None:
                problems.append(f"item {item_label}: missing required field '{field}'")

        status = item.get("status")
        if status is not None:
            if status not in valid_statuses:
                problems.append(
                    f"item {item_label}: invalid status '{status}' (must be open, partial, done, n/a)"
                )
            elif status in {"done", "partial"}:
                ev = item.get("evidence")
                valid_evidence = False
                if isinstance(ev, str) and ev.strip():
                    ev_str = ev.strip()
                    if ev_str.startswith("just "):
                        rest = ev_str[len("just ") :].strip()
                        recipe = rest.split()[0] if rest else ""
                        if recipe and _has_just_recipe(project_path, recipe):
                            valid_evidence = True
                    elif (project_path / ev_str).exists():
                        valid_evidence = True

                if not valid_evidence:
                    id_name = item_id if item_id else item_label
                    problems.append(f"{id_name}: false claim — evidence {ev} not found")

    ideas = data.get("ideas") if isinstance(data, dict) and "ideas" in data else []
    if not isinstance(ideas, list):
        problems.append("`ideas` must be a list")
    else:
        valid_idea_statuses = {"untested", "testing", "paid-off", "dropped"}
        for idx, item in enumerate(ideas):
            if not isinstance(item, dict):
                problems.append(f"idea item {idx}: not a mapping")
                continue

            item_id = item.get("id")
            item_label = f"'{item_id}'" if item_id else f"at index {idx}"

            for field in ("id", "idea", "from", "test", "kill"):
                if field not in item or item[field] is None:
                    problems.append(f"idea {item_label}: missing required field '{field}'")

            status = item.get("status")
            if status is not None and status not in valid_idea_statuses:
                problems.append(
                    f"idea {item_label}: invalid status '{status}' (must be untested, testing, paid-off, dropped)"
                )

    return problems


def summary(project: Path | str, top: int = 5) -> str:
    project_path = Path(project)
    standards_path = project_path / "STANDARDS.md"
    if not standards_path.exists():
        return "standards: no STANDARDS.md — run the expert-bar skill to write the expert bar for this project's domain"

    try:
        data = load(project_path)
    except StandardsError as exc:
        reason = str(exc).splitlines()[0] if str(exc).splitlines() else "unknown error"
        return f"standards: cannot parse STANDARDS.md — {reason}"

    standards = data.get("standards") or []
    m_total = len(standards)
    n_open = sum(1 for s in standards if isinstance(s, dict) and s.get("status") in {"open", "partial"})

    problems = validate(data, project_path)
    if problems:
        first = next((p for p in problems if "false claim" in p), problems[0])
        count = len(problems)
        count_str = f"{count} problem" if count == 1 else f"{count} problems"
        first_line = f"standards: {count_str} — {first}"
    else:
        phase = data.get("phase")
        if phase:
            first_line = f"standards: {n_open} open of {m_total} (phase: {phase})"
        else:
            first_line = f"standards: {n_open} open of {m_total}"

        ideas = data.get("ideas")
        if isinstance(ideas, list):
            n_untested = sum(
                1
                for i in ideas
                if isinstance(i, dict) and i.get("status") in {None, "untested"}
            )
            if n_untested > 0:
                suffix = "idea untested" if n_untested == 1 else "ideas untested"
                first_line += f" · {n_untested} {suffix}"

    gap_lines: list[str] = []
    for item in standards:
        if isinstance(item, dict) and item.get("status") in {"open", "partial"}:
            gap_lines.append(f"  - {item.get('id')} [{item.get('status')}]: {item.get('bar')}")
            if len(gap_lines) == top:
                break

    lines = [first_line] + gap_lines
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", default=".", help="project directory")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate standards and exit nonzero on failure",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="print summary (default)",
    )
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if args.check:
        try:
            data = load(project)
        except StandardsError as exc:
            print(f"standards: cannot load STANDARDS.md — {exc}", file=sys.stderr)
            return 2
        problems = validate(data, project)
        if problems:
            for p in problems:
                print(p)
            return 1
        return 0
    else:
        print(summary(project))
        return 0


if __name__ == "__main__":
    sys.exit(main())

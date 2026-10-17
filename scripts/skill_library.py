#!/usr/bin/env python3
"""Skill library: whole third-party skill collections kept on disk, outside every folder an
agent loads skills from, so they cost no tokens until one is pulled in.

    just skill-lib sync                 # clone or update every library
    just skill-lib list [filter]        # what's on the shelf
    just skill-lib add <skill>          # scan, then vendor into global-skills/ with
                                        # LICENSE + UPSTREAM; then run `just skills`

The library root is a sibling of this repo (`<parent>/skill-library`, override with
SKILL_LIBRARY). It must never be inside the repo: indexing a nested clone replaces the
Refinery's own jcodemunch index.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARIES = {
    "scientific-agent-skills": "https://github.com/K-Dense-AI/scientific-agent-skills.git",
}
SEVERITY = ["SAFE", "INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class SkillLibraryError(Exception):
    pass


def default_root(repo_root: Path = REPO_ROOT) -> Path:
    env = os.environ.get("SKILL_LIBRARY")
    return Path(env) if env else Path(repo_root).resolve().parent / "skill-library"


def _frontmatter(skill_md: Path) -> dict:
    m = re.match(r"^---\n(.*?)\n---", skill_md.read_text(encoding="utf-8"), re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def _skill_dirs(root: Path):
    for lib in sorted(p for p in Path(root).iterdir() if p.is_dir()):
        skills = lib / "skills"
        if not skills.is_dir():
            continue
        for d in sorted(p for p in skills.iterdir() if (p / "SKILL.md").is_file()):
            yield lib, d


def list_skills(root: Path, filt: str = "") -> list:
    rows = []
    for lib, d in _skill_dirs(root):
        desc = _frontmatter(d / "SKILL.md").get("description", "")
        if filt.lower() in f"{d.name} {desc}".lower():
            rows.append((lib.name, d.name, desc))
    return rows


def scan_allows(severity: str) -> bool:
    return severity in ("SAFE", "INFO", "LOW")


def scan_with_cisco(path: Path):
    """Run the upstream-recommended scanner in an isolated uvx env. Returns
    (max_severity, detail), or (None, why) when the scanner can't run."""
    try:
        r = subprocess.run(["uvx", "--from", "cisco-ai-skill-scanner", "skill-scanner", "scan",
                            str(path), "--use-behavioral", "--format", "json"],
                           capture_output=True, text=True, timeout=600, cwd="/tmp")
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)
    try:
        start = r.stdout.index("{")
        data = json.loads(r.stdout[start:])
    except ValueError:
        return None, (r.stderr or r.stdout)[-300:]
    sevs = [str(f.get("severity", "")).upper() for f in data.get("findings", [])]
    sevs = [s for s in sevs if s in SEVERITY] or ["SAFE"]
    worst = max(sevs, key=SEVERITY.index)
    detail = "; ".join(f"{f.get('severity')} {f.get('rule_id', '')}"
                       for f in data.get("findings", []))
    return worst, detail


def _git_commit(lib: Path):
    r = subprocess.run(["git", "-C", str(lib), "log", "-1", "--format=%h %cs"],
                       capture_output=True, text=True)
    parts = r.stdout.split()
    return (parts[0], parts[1]) if len(parts) == 2 else ("unknown", "unknown")


def _git_remote(lib: Path) -> str:
    r = subprocess.run(["git", "-C", str(lib), "remote", "get-url", "origin"],
                       capture_output=True, text=True)
    return re.sub(r"\.git$", "", r.stdout.strip()) or str(lib)


def _license_text(lib: Path) -> str:
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt"):
        if (lib / name).is_file():
            return (lib / name).read_text(encoding="utf-8")
    raise SkillLibraryError(f"no LICENSE file in {lib}; not vendoring without one")


def add_skill(root: Path, name: str, dest: Path, scan=scan_with_cisco,
              commit=_git_commit, remote=_git_remote) -> Path:
    if not _NAME.match(name):
        raise SkillLibraryError(f"not a skill name: {name!r}")
    found = [(lib, d) for lib, d in _skill_dirs(root) if d.name == name]
    if not found:
        raise SkillLibraryError(f"skill {name!r} not found under {root}; try `list`")
    lib, src = found[0]
    target = Path(dest) / name
    if target.exists():
        raise SkillLibraryError(f"{target} already exists; remove it first to re-vendor")
    if scan is None:
        scan_line = "Scan: skipped (--no-scan)"
    else:
        worst, detail = scan(src)
        if worst is None:
            raise SkillLibraryError(f"skill scanner couldn't run ({detail}); "
                                    "re-run with --no-scan only after reading every file")
        if not scan_allows(worst):
            raise SkillLibraryError(f"scan found {worst}: {detail}; not vendored")
        scan_line = f"Scan: {worst} (cisco-ai-skill-scanner --use-behavioral)" + (
            f" — {detail}" if detail else "")
    licence = _license_text(lib)
    sha, date = commit(lib)
    shutil.copytree(src, target, symlinks=False)
    (target / "LICENSE").write_text(licence, encoding="utf-8")
    spdx = _frontmatter(src / "SKILL.md").get("license", "see LICENSE")
    (target / "UPSTREAM").write_text(
        f"Vendored from {remote(lib)}\nPath: skills/{name}\nCommit: {sha} ({date})\n"
        f"License: {spdx} (repository LICENSE copied as LICENSE)\n{scan_line}\n",
        encoding="utf-8")
    return target


def sync(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, url in LIBRARIES.items():
        lib = root / name
        if lib.is_dir():
            subprocess.run(["git", "-C", str(lib), "pull", "-q", "--ff-only"], check=True)
            print(f"updated {lib}")
        else:
            subprocess.run(["git", "clone", "-q", url, str(lib)], check=True)
            print(f"cloned {lib}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Skill library: keep collections on disk, "
                                             "vendor one skill at a time.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync")
    p_list = sub.add_parser("list")
    p_list.add_argument("filter", nargs="?", default="")
    p_add = sub.add_parser("add")
    p_add.add_argument("skill")
    p_add.add_argument("--no-scan", action="store_true")
    a = ap.parse_args(argv)
    root = default_root()
    try:
        if a.cmd == "sync":
            sync(root)
        elif a.cmd == "list":
            rows = list_skills(root, a.filter) if root.is_dir() else []
            for lib, name, desc in rows:
                print(f"{name:32} {desc[:100]}  [{lib}]")
            print(f"{len(rows)} skill(s) in {root}" + ("" if root.is_dir() else
                                                       " — run `just skill-lib sync`"))
        else:
            out = add_skill(root, a.skill, REPO_ROOT / "global-skills",
                            scan=None if a.no_scan else scan_with_cisco)
            print(f"vendored {out}\nnext: read it, then `just skills` to link and list it")
    except SkillLibraryError as e:
        print(f"skill-lib: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

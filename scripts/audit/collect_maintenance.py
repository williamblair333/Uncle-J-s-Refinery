# scripts/audit/collect_maintenance.py
"""Collector B: maintenance burden per component from git history (90 days).

A commit is 'maintenance' when its subject starts with fix/hotfix/revert/repair/corrupt —
i.e., the stack maintaining itself rather than gaining capability. Commit→component
mapping reuses the manifest keywords + file globs. Commits matching no component
are counted under _unmatched so coverage gaps are visible.

A commit matching N components is counted once in each — per-component sums intentionally exceed total_commits.
"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import audit_lib

REPO = Path(__file__).resolve().parents[2]
# Maintenance = the subject STARTS with a fix/repair verb. Mid-subject mentions
# ("feat: add nightly repair cron", "docs: ... repair notes", merge subjects with
# fix/ branch names) are capability or documentation, not burden.
MAINT_RE = re.compile(r"^(fix|hotfix|revert|repair|corrupt)\b", re.I)


def parse_log(text):
    """Parse `git log --pretty=%h|%ad|%s --date=short --name-only` output.

    Real git output places a blank line between the header and the file list
    within each commit, and another blank line between commits.  The test
    fixture uses a compact format (no intra-commit blank line) where the file
    list follows immediately.  This parser handles both layouts by scanning
    line-by-line: a header pattern opens a new commit; subsequent non-empty
    lines accumulate as file paths; blank lines are ignored.

    The subject may itself contain ``|`` — ``split("|", 2)`` preserves it.
    """
    HEADER = re.compile(r"^(\S+)\|(\d{4}-\d{2}-\d{2})\|(.+)$")
    commits, current = [], None
    for line in text.splitlines():
        stripped = line.strip()
        m = HEADER.match(stripped)
        if m:
            if current:
                commits.append(current)
            current = (m.group(1), m.group(2), m.group(3), [])
        elif stripped and current:
            current[3].append(stripped)
        # blank lines are silently skipped
    if current:
        commits.append(current)
    return commits


def is_maintenance(subject):
    return bool(MAINT_RE.search(subject))


def aggregate(components, commits):
    agg = {c["id"]: {"commits": 0, "maintenance_commits": 0} for c in components}
    agg["_unmatched"] = {"commits": 0, "maintenance_commits": 0}
    for _, _, subject, files in commits:
        targets = audit_lib.match_components(components, subject, files) or {"_unmatched"}
        for t in targets:
            agg[t]["commits"] += 1
            agg[t]["maintenance_commits"] += int(is_maintenance(subject))
    for v in agg.values():
        v["maintenance_share"] = round(v["maintenance_commits"] / v["commits"], 2) if v["commits"] else 0.0
    return agg


def main():
    comps = audit_lib.load_components(REPO / "scripts/audit/components.json")
    try:
        log = subprocess.run(
            ["git", "-C", str(REPO), "log", "--since=90.days",
             "--pretty=%h|%ad|%s", "--date=short", "--name-only"],
            capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        sys.exit("collect_maintenance: git not found on PATH")
    except subprocess.CalledProcessError as e:
        sys.exit(f"collect_maintenance: git failed (rc={e.returncode}): {e.stderr.strip()}")
    commits = parse_log(log)
    result = {"window_days": 90,
              "total_commits": len(commits),  # deduplicated; per-component sums exceed this when a commit matches multiple components
              "components": aggregate(comps, commits)}
    out = audit_lib.write_json(REPO / "state/payoff-audit/maintenance.json", result)
    print(f"maintenance: {out} ({len(commits)} commits)")


if __name__ == "__main__":
    main()

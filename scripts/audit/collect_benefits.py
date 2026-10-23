# scripts/audit/collect_benefits.py
"""Collector C: benefit signals per component. Every source that can't be read
is listed in `missing` — explicit gaps, no guesses.

Sources:
  1. state/hook-blocks.log (+ archives)     -> guard catches (guardrails-discipline)
  2. ~/.code-index/**/*.json scanned for the maximum tokens_saved value
  3. MemPalace SQLite (~/.mempalace/palace/chroma.sqlite3) -> embedding row count (read-only)
  4. state/ralph-runs.log (one line per ralph-harness run) -> run count, last run
"""
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import audit_lib

HOME = Path.home()
REPO = Path(__file__).resolve().parents[2]
GUARD_RE = re.compile(r"([a-z0-9][a-z0-9_]*(?:-[a-z0-9_]+)*-guard(?:-[a-z0-9_]+)*)", re.I)


def count_blocks(text):
    """Count BLOCKED guard events by guard name.

    Only lines containing the word BLOCKED are counted; ALLOWED lines and
    other non-BLOCKED log entries are silently skipped.  Lines that are
    BLOCKED but contain no recognisable guard name token are tallied under
    ``_unparsed``.
    """
    counts = {}
    for line in filter(str.strip, text.splitlines()):
        if "BLOCKED" not in line:
            continue
        m = GUARD_RE.search(line)
        key = m.group(1).lower() if m else "_unparsed"
        counts[key] = counts.get(key, 0) + 1
    return counts


ARCHIVE_RE = re.compile(r"hook-blocks\.log\.\d{8}(-\d{6}-\d+)?")


def block_log_files(state_dir):
    """The live hook-blocks.log plus its rotated archives, oldest first.

    The guards archive the log to hook-blocks.log.YYYYMMDD[-HHMMSS-PID] past 1 MiB
    (hook_log_append, 2026-10-22). Hand-made copies such as `.bak-2026-10-16`
    duplicate the live log and are excluded.
    """
    state_dir = Path(state_dir)
    files = sorted(p for p in state_dir.glob("hook-blocks.log.*")
                   if ARCHIVE_RE.fullmatch(p.name) and p.is_file())
    live = state_dir / "hook-blocks.log"
    if live.is_file():
        files.append(live)
    return files


def jcodemunch_saved_tokens():
    """Best-effort scan of ~/.code-index for a persisted tokens_saved figure."""
    best = None
    root = HOME / ".code-index"
    if not root.exists():
        return None
    for p in root.glob("**/*.json"):
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        for m in re.finditer(r'"(?:total_)?tokens_saved"\s*:\s*(\d+)', text):
            best = max(best or 0, int(m.group(1)))
    return best


def mempalace_counts(db_path):
    if not db_path.exists():
        return None
    uri = f"file:{db_path}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            n = conn.execute("SELECT count(*) FROM embeddings").fetchone()[0]
    except sqlite3.Error:
        return None
    return {"embeddings_rows": n}


def ralph_runs(log_path):
    """{'runs': N, 'last_run': ISO} from state/ralph-runs.log; None if absent/unreadable."""
    try:
        lines = [ln for ln in Path(log_path).read_text(errors="replace").splitlines()
                 if " start " in ln]
    except OSError:
        return None
    return {"runs": len(lines), "last_run": lines[-1].split(" ", 1)[0] if lines else None}


def main():
    missing, result = [], {"components": {}}

    block_logs = block_log_files(REPO / "state")
    if block_logs:
        text = "".join(p.read_text(errors="replace") for p in block_logs)
        result["components"]["guardrails-discipline"] = {
            "hook_blocks": count_blocks(text), "log_files": len(block_logs)}
    else:
        missing.append(str(REPO / "state/hook-blocks.log"))

    saved = jcodemunch_saved_tokens()
    if saved is not None:
        result["components"]["jmunch-retrieval"] = {"tokens_saved_best": saved}
    else:
        missing.append("~/.code-index tokens_saved")

    # Live palace (verified 2026-06-11). ~/.mempalace/chroma.sqlite3 is a stale stub — do not use.
    db = HOME / ".mempalace/palace/chroma.sqlite3"
    mp = mempalace_counts(db)
    if mp and mp["embeddings_rows"] > 0:
        result["components"]["mempalace"] = {**mp, "db_path": str(db)}
    elif mp:  # readable but empty — suspicious for a live palace; flag, don't report a confident 0
        missing.append(f"{db}: readable but 0 embeddings — likely wrong/stale DB, verify path")
    else:
        missing.append(str(db))

    # ralph: the Phase 4 D3 gate ("remove only if the usage counter confirms idle").
    # ralph-harness.sh appends one line per real run since 2026-10-23; no file means
    # "not measured", never "idle".
    rr = ralph_runs(REPO / "state/ralph-runs.log")
    if rr is not None:
        result["components"]["ralph"] = rr
    else:
        missing.append(str(REPO / "state/ralph-runs.log"))

    result["missing"] = missing
    out =audit_lib.write_json(REPO / "state/payoff-audit/benefits.json", result)
    print(f"benefits: {out} (missing: {len(missing)})")


if __name__ == "__main__":
    main()

# scripts/audit/collect_benefits.py
"""Collector C: benefit signals per component. Every source that can't be read
is listed in `missing` — explicit gaps, no guesses.

Sources:
  1. state/hook-blocks.log                  -> guard catches (guardrails-discipline)
  2. ~/.code-index/**/*.json scanned for the maximum tokens_saved value
  3. MemPalace SQLite (~/.mempalace/palace/chroma.sqlite3) -> embedding row count (read-only)
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


def count_corrections(text):
    """Count correction-ledger events per component. Tolerates non-JSON lines
    (counted under _unparsed) so a truncated ledger never crashes the audit."""
    import json
    counts = {}
    for line in filter(str.strip, text.splitlines()):
        try:
            ev = json.loads(line)
            comp = ev.get("component") or "_uncategorized"
        except (ValueError, AttributeError):
            comp = "_unparsed"
        counts[comp] = counts.get(comp, 0) + 1
    return counts


def iso_age_days(ts_str, now=None):
    """Age in calendar days of an ISO-8601 'Z' timestamp; None if unparseable."""
    import datetime
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        t = datetime.datetime.strptime(ts_str.strip(), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc)
    except (ValueError, AttributeError):
        return None
    return float((now.date() - t.date()).days)


def count_matching(text, needle):
    return sum(1 for line in text.splitlines() if needle in line)


def dreaming_run_stats(text):
    runs = count_matching(text, "dreamed:")
    skips = count_matching(text, "skip:")
    return {"runs": runs, "skips": skips}


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


def main():
    missing, result = [], {"components": {}}

    blocks_path = REPO / "state/hook-blocks.log"
    if blocks_path.exists():
        result["components"].setdefault("guardrails-discipline", {})
        result["components"]["guardrails-discipline"]["hook_blocks"] = \
            count_blocks(blocks_path.read_text(errors="replace"))
    else:
        missing.append(str(blocks_path))

    corr_path = REPO / "state/corrections.jsonl"
    if corr_path.exists():
        result["components"].setdefault("guardrails-discipline", {})
        result["components"]["guardrails-discipline"]["corrections"] = \
            count_corrections(corr_path.read_text(errors="replace"))
    else:
        missing.append(str(corr_path))

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

    # dreaming: last-run age + run/skip counts
    last_run = REPO / "state/dreaming-last-run.txt"
    dream_log = REPO / "state/dreaming.log"
    dream = {}
    if last_run.exists():
        age = iso_age_days(last_run.read_text())
        if age is not None:
            dream["last_run_age_days"] = age
    if dream_log.exists():
        dream.update(dreaming_run_stats(dream_log.read_text(errors="replace")))
    if dream:
        result["components"]["dreaming"] = dream
    else:
        missing.append("dreaming logs (state/dreaming-last-run.txt, state/dreaming.log)")

    # telegram: poll count as a liveness proxy
    tg_log = REPO / "state/telegram-gateway.log"
    if tg_log.exists():
        result["components"]["telegram"] = {
            "poll_count": count_matching(tg_log.read_text(errors="replace"), "Polling Telegram")}
    else:
        missing.append(str(tg_log))

    # ralph: no log shipped (verified 2026-06-11). Explicit gap — never guessed.
    missing.append("ralph: no run log present in state/ (verify if/when ralph logging lands)")

    result["missing"] = missing
    out = audit_lib.write_json(REPO / "state/payoff-audit/benefits.json", result)
    print(f"benefits: {out} (missing: {len(missing)})")


if __name__ == "__main__":
    main()

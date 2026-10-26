#!/usr/bin/env python3
"""Report on offloaded model calls: agy, Heretic, and local models vs Claude.

Aggregates execution logs from delegate.jsonl, ask_local.jsonl, and Claude
subagent allow/deny checks to measure offloading activity and reliability.

Usage:
    scripts/offload_report.py [--days N] [--json]
    scripts/offload_report.py --delegate PATH --ask-local PATH --offload-check PATH
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
DEFAULT_DELEGATE = _REPO / "state" / "delegate.jsonl"
DEFAULT_ASK_LOCAL = _REPO / "state" / "ask_local.jsonl"
DEFAULT_OFFLOAD_CHECK = Path.home() / ".claude" / "state" / "offload-check.jsonl"


def parse_ts(val: Any) -> tuple[float, str] | None:
    """Return (unix_ts, YYYY-MM-DD) in UTC, or None if invalid."""
    if isinstance(val, (int, float)):
        if val <= 0:
            return None
        try:
            dt = datetime.fromtimestamp(val, tz=timezone.utc)
            return float(val), dt.strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            return None
    elif isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_utc = dt.astimezone(timezone.utc)
            return dt_utc.timestamp(), dt_utc.strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            return None
    return None


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    """Read a JSONL file, ignoring non-existent files and skipping malformed lines."""
    p = Path(path)
    if not p.is_file():
        return []
    records: list[dict[str, Any]] = []
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        records.append(obj)
                except Exception:
                    continue
    except OSError:
        return []
    return records


def classify_backend(rec: dict[str, Any], source: str) -> str:
    """Classify record into backend identifier."""
    if source == "ask_local":
        model = str(rec.get("model") or "unknown").strip()
        return f"ask_local:{model}"

    backend = str(rec.get("backend") or "unknown").strip()
    model = str(rec.get("model") or "").strip()

    if backend == "agy":
        return f"agy:{model}" if model else "agy"
    elif backend == "heretic":
        return "heretic"
    elif backend.startswith("local:"):
        return backend
    elif backend == "local":
        if model.startswith("local:"):
            return model
        return f"local:{model}" if model else "local"
    return f"{backend}:{model}" if model else backend


def is_quota_exhausted(error_str: str) -> bool:
    """Return True if the error indicates quota exhaustion."""
    s = (error_str or "").lower()
    return any(k in s for k in ("status error", "quota", "resource_exhausted", "individual quota reached"))


def _init_stats() -> dict[str, Any]:
    return {"calls": 0, "ok": 0, "failed": 0, "seconds": 0.0}


def _update_stats(stats: dict[str, Any], ok: bool, seconds: float) -> None:
    stats["calls"] += 1
    if ok:
        stats["ok"] += 1
    else:
        stats["failed"] += 1
    stats["seconds"] += seconds


def generate_report(
    delegate_path: Path | str = DEFAULT_DELEGATE,
    ask_local_path: Path | str = DEFAULT_ASK_LOCAL,
    offload_check_path: Path | str = DEFAULT_OFFLOAD_CHECK,
    days: int = 7,
    now: float | None = None,
) -> dict[str, Any]:
    """Generate offload aggregation report."""
    curr_now = time.time() if now is None else float(now)
    cutoff_ts = curr_now - (days * 86400.0) if days > 0 else 0.0

    total_stats = _init_stats()
    total_backends: dict[str, dict[str, Any]] = {}

    by_day_stats: dict[str, dict[str, Any]] = {}
    by_day_backends: dict[str, dict[str, dict[str, Any]]] = {}

    agy_errors: dict[str, int] = {}
    agy_fail_total = 0
    quota_exhausted_count = 0

    mcp_tool_calls = 0
    shell_file_tool_calls = 0

    # 1. Process delegate.jsonl
    for rec in read_jsonl(delegate_path):
        ts_res = parse_ts(rec.get("ts"))
        if ts_res is None:
            continue
        unix_ts, day_str = ts_res
        if days > 0 and unix_ts < cutoff_ts:
            continue
        if "backend" not in rec and "model" not in rec:
            continue

        ok = bool(rec.get("ok"))
        try:
            sec = max(0.0, float(rec.get("seconds", 0.0)))
        except (ValueError, TypeError):
            sec = 0.0

        backend = classify_backend(rec, source="delegate")

        # Update totals
        _update_stats(total_stats, ok, sec)
        if backend not in total_backends:
            total_backends[backend] = _init_stats()
        _update_stats(total_backends[backend], ok, sec)

        # Update daily
        if day_str not in by_day_stats:
            by_day_stats[day_str] = _init_stats()
            by_day_backends[day_str] = {}
        _update_stats(by_day_stats[day_str], ok, sec)
        if backend not in by_day_backends[day_str]:
            by_day_backends[day_str][backend] = _init_stats()
        _update_stats(by_day_backends[day_str][backend], ok, sec)

        # agy breakdowns
        raw_backend = str(rec.get("backend") or "").strip()
        if raw_backend == "agy":
            if not ok:
                agy_fail_total += 1
                err = str(rec.get("error") or "unknown").strip()
                err_trunc = err[:60]
                agy_errors[err_trunc] = agy_errors.get(err_trunc, 0) + 1
                if is_quota_exhausted(err):
                    quota_exhausted_count += 1

            tools = rec.get("tools")
            if isinstance(tools, dict):
                for tname, cnt in tools.items():
                    try:
                        c = int(cnt)
                    except (ValueError, TypeError):
                        continue
                    if tname.startswith("mcp:") or tname == "mcp":
                        mcp_tool_calls += c
                    else:
                        shell_file_tool_calls += c

    # 2. Process ask_local.jsonl
    for rec in read_jsonl(ask_local_path):
        ts_res = parse_ts(rec.get("ts"))
        if ts_res is None:
            continue
        unix_ts, day_str = ts_res
        if days > 0 and unix_ts < cutoff_ts:
            continue
        if "tool" not in rec and "model" not in rec:
            continue

        ok = bool(rec.get("ok"))
        try:
            sec = max(0.0, float(rec.get("seconds", 0.0)))
        except (ValueError, TypeError):
            sec = 0.0

        backend = classify_backend(rec, source="ask_local")

        # Update totals
        _update_stats(total_stats, ok, sec)
        if backend not in total_backends:
            total_backends[backend] = _init_stats()
        _update_stats(total_backends[backend], ok, sec)

        # Update daily
        if day_str not in by_day_stats:
            by_day_stats[day_str] = _init_stats()
            by_day_backends[day_str] = {}
        _update_stats(by_day_stats[day_str], ok, sec)
        if backend not in by_day_backends[day_str]:
            by_day_backends[day_str][backend] = _init_stats()
        _update_stats(by_day_backends[day_str][backend], ok, sec)

    # 3. Process offload-check.jsonl
    subagents_allowed = 0
    subagents_denied = 0
    for rec in read_jsonl(offload_check_path):
        ts_res = parse_ts(rec.get("ts"))
        if ts_res is None:
            continue
        unix_ts, _ = ts_res
        if days > 0 and unix_ts < cutoff_ts:
            continue
        decision = str(rec.get("decision") or "").strip().lower()
        if decision == "allow":
            subagents_allowed += 1
        elif decision == "deny":
            subagents_denied += 1

    # Round seconds in data structures
    total_stats["seconds"] = round(total_stats["seconds"], 1)
    for b in total_backends.values():
        b["seconds"] = round(b["seconds"], 1)

    by_day_formatted: dict[str, dict[str, Any]] = {}
    for day in sorted(by_day_stats.keys()):
        d_stats = by_day_stats[day]
        d_stats["seconds"] = round(d_stats["seconds"], 1)
        d_backends = by_day_backends[day]
        for b in d_backends.values():
            b["seconds"] = round(b["seconds"], 1)
        # Sort day backends by calls desc, then name
        sorted_backends = dict(sorted(d_backends.items(), key=lambda kv: (-kv[1]["calls"], kv[0])))
        by_day_formatted[day] = {
            "calls": d_stats["calls"],
            "ok": d_stats["ok"],
            "failed": d_stats["failed"],
            "seconds": d_stats["seconds"],
            "backends": sorted_backends,
        }

    # Sort total backends by calls desc, then name
    sorted_total_backends = dict(sorted(total_backends.items(), key=lambda kv: (-kv[1]["calls"], kv[0])))

    # Sort agy error breakdown by count desc, then error text
    sorted_agy_errors = dict(sorted(agy_errors.items(), key=lambda kv: (-kv[1], kv[0])))

    # Tool tally share
    tool_total = mcp_tool_calls + shell_file_tool_calls
    mcp_share = round(mcp_tool_calls / tool_total, 4) if tool_total > 0 else 0.0

    headline = (
        f"offloaded {total_stats['calls']} calls ({total_stats['ok']} ok) in {days} days; "
        f"Claude subagents allowed {subagents_allowed}, redirected {subagents_denied}"
    )

    return {
        "headline": headline,
        "days": days,
        "calls": total_stats["calls"],
        "ok": total_stats["ok"],
        "failed": total_stats["failed"],
        "seconds": total_stats["seconds"],
        "total": {
            "calls": total_stats["calls"],
            "ok": total_stats["ok"],
            "failed": total_stats["failed"],
            "seconds": total_stats["seconds"],
            "backends": sorted_total_backends,
        },
        "by_day": by_day_formatted,
        "agy_failures": {
            "total": agy_fail_total,
            "quota_exhausted": quota_exhausted_count,
            "by_error": sorted_agy_errors,
        },
        "agy_tools": {
            "mcp": mcp_tool_calls,
            "shell_file": shell_file_tool_calls,
            "total": tool_total,
            "mcp_share": mcp_share,
        },
        "subagents": {
            "allowed": subagents_allowed,
            "denied": subagents_denied,
            "redirected": subagents_denied,
            "total": subagents_allowed + subagents_denied,
        },
    }


def format_text_report(report: dict[str, Any]) -> str:
    """Format the report dictionary as a plain-text table report."""
    lines: list[str] = [report["headline"], ""]

    lines.append(f"{'Date':<12} {'Backend':<32} {'Calls':>7} {'OK':>6} {'Failed':>7} {'Time (s)':>10}")
    lines.append("-" * 78)

    by_day = report.get("by_day", {})
    if not by_day:
        lines.append("(no offload calls in window)")
    else:
        for day, d_data in by_day.items():
            lines.append(
                f"{day:<12} {'[Day Total]':<32} {d_data['calls']:>7} {d_data['ok']:>6} "
                f"{d_data['failed']:>7} {d_data['seconds']:>10.1f}"
            )
            for b_name, b_data in d_data.get("backends", {}).items():
                lines.append(
                    f"{'':<12} {b_name:<32} {b_data['calls']:>7} {b_data['ok']:>6} "
                    f"{b_data['failed']:>7} {b_data['seconds']:>10.1f}"
                )

    lines.append("-" * 78)
    total = report.get("total", {})
    lines.append(
        f"{'Total':<12} {'':<32} {total.get('calls', 0):>7} {total.get('ok', 0):>6} "
        f"{total.get('failed', 0):>7} {total.get('seconds', 0.0):>10.1f}"
    )
    for b_name, b_data in total.get("backends", {}).items():
        lines.append(
            f"{'':<12} {b_name:<32} {b_data['calls']:>7} {b_data['ok']:>6} "
            f"{b_data['failed']:>7} {b_data['seconds']:>10.1f}"
        )

    # agy tool tally
    tools = report.get("agy_tools", {})
    mcp_calls = tools.get("mcp", 0)
    shell_calls = tools.get("shell_file", 0)
    tot_tools = tools.get("total", 0)
    share_pct = (tools.get("mcp_share", 0.0) * 100.0) if tot_tools > 0 else 0.0

    lines.append("")
    lines.append("Antigravity (agy) Tool Tally:")
    lines.append(f"  MCP calls:         {mcp_calls:>6}")
    lines.append(f"  Shell/file calls:  {shell_calls:>6}")
    lines.append(f"  Total calls:       {tot_tools:>6}")
    lines.append(f"  Stack (MCP) share: {share_pct:>6.1f}%")

    # agy failures
    fails = report.get("agy_failures", {})
    lines.append("")
    lines.append("Antigravity (agy) Failures:")
    lines.append(f"  Total failures:    {fails.get('total', 0):>6}")
    lines.append(f"  Quota exhausted:   {fails.get('quota_exhausted', 0):>6}")
    by_err = fails.get("by_error", {})
    if by_err:
        lines.append("  By error:")
        for err_str, count in by_err.items():
            lines.append(f"    {err_str:<62} {count:>5}")

    # Claude subagents
    subs = report.get("subagents", {})
    lines.append("")
    lines.append("Claude Subagent Spawns:")
    lines.append(f"  Allowed:           {subs.get('allowed', 0):>6}")
    lines.append(f"  Denied/redirected: {subs.get('denied', 0):>6}")
    lines.append(f"  Total:             {subs.get('total', 0):>6}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=7, help="number of days to report (default 7)")
    ap.add_argument("--json", action="store_true", help="output as JSON object")
    ap.add_argument("--delegate", default=str(DEFAULT_DELEGATE), help="path to delegate.jsonl")
    ap.add_argument("--ask-local", default=str(DEFAULT_ASK_LOCAL), help="path to ask_local.jsonl")
    ap.add_argument("--offload-check", default=str(DEFAULT_OFFLOAD_CHECK), help="path to offload-check.jsonl")
    args = ap.parse_args(argv)

    report = generate_report(
        delegate_path=args.delegate,
        ask_local_path=args.ask_local,
        offload_check_path=args.offload_check,
        days=args.days,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_text_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import importlib.util
import json
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("offload_report", REPO / "scripts" / "offload_report.py")
offload = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(offload)


def test_mixed_backends_classification(tmp_path: Path):
    del_file = tmp_path / "delegate.jsonl"
    al_file = tmp_path / "ask_local.jsonl"
    oc_file = tmp_path / "offload-check.jsonl"

    now = 1792940000.0  # reference time

    del_lines = [
        {"ts": now - 100, "backend": "agy", "model": "gemini-4-argon-high", "seconds": 12.0, "ok": True},
        {"ts": now - 200, "backend": "heretic", "model": "heretic", "seconds": 5.0, "ok": True},
        {"ts": now - 300, "backend": "local", "model": "local:heretic", "seconds": 3.0, "ok": False, "error": "failed"},
        {"ts": now - 400, "backend": "local:ask_local", "model": "", "seconds": 2.5, "ok": True},
        {"ts": now - 500, "backend": "openai", "model": "gpt-4o", "seconds": 8.0, "ok": True},
    ]
    del_file.write_text("\n".join(json.dumps(x) for x in del_lines) + "\n")

    al_lines = [
        {"ts": "2026-10-25T14:00:00Z", "tool": "summarize", "model": "qwen3.5:9b", "ok": True, "seconds": 4.5},
        {"ts": "2026-10-25T14:05:00+00:00", "tool": "extract", "model": "heretic", "ok": False, "error": "err", "seconds": 1.5},
    ]
    al_file.write_text("\n".join(json.dumps(x) for x in al_lines) + "\n")

    oc_lines = [
        {"ts": "2026-10-25T14:10:00Z", "decision": "allow", "subagent_type": "research"},
        {"ts": "2026-10-25T14:15:00Z", "decision": "deny", "subagent_type": "general-purpose"},
        {"ts": "2026-10-25T14:20:00Z", "decision": "deny", "subagent_type": "swe"},
    ]
    oc_file.write_text("\n".join(json.dumps(x) for x in oc_lines) + "\n")

    report = offload.generate_report(
        delegate_path=del_file,
        ask_local_path=al_file,
        offload_check_path=oc_file,
        days=7,
        now=now,
    )

    # 5 from delegate + 2 from ask_local = 7 total calls
    assert report["total"]["calls"] == 7
    assert report["total"]["ok"] == 5
    assert report["total"]["failed"] == 2
    assert report["total"]["seconds"] == 36.5

    backends = report["total"]["backends"]
    assert "agy:gemini-4-argon-high" in backends
    assert backends["agy:gemini-4-argon-high"]["calls"] == 1
    assert backends["agy:gemini-4-argon-high"]["ok"] == 1

    assert "heretic" in backends
    assert backends["heretic"]["calls"] == 1

    assert "local:heretic" in backends
    assert backends["local:heretic"]["calls"] == 1
    assert backends["local:heretic"]["failed"] == 1

    assert "local:ask_local" in backends
    assert backends["local:ask_local"]["calls"] == 1

    assert "openai:gpt-4o" in backends
    assert backends["openai:gpt-4o"]["calls"] == 1

    assert "ask_local:qwen3.5:9b" in backends
    assert backends["ask_local:qwen3.5:9b"]["calls"] == 1
    assert backends["ask_local:qwen3.5:9b"]["ok"] == 1

    assert "ask_local:heretic" in backends
    assert backends["ask_local:heretic"]["calls"] == 1
    assert backends["ask_local:heretic"]["failed"] == 1

    # Claude subagents
    assert report["subagents"]["allowed"] == 1
    assert report["subagents"]["denied"] == 2
    assert report["subagents"]["total"] == 3


def test_malformed_lines_handling(tmp_path: Path):
    del_file = tmp_path / "delegate.jsonl"
    al_file = tmp_path / "ask_local.jsonl"
    oc_file = tmp_path / "offload-check.jsonl"

    now = 1792940000.0

    # Write corrupt and valid lines mixed
    del_content = (
        "not json at all\n"
        "\n"
        "{}\n"
        '{"ts": -50, "backend": "agy"}\n'
        '{"ts": "invalid-date", "backend": "agy"}\n'
        f'{{"ts": {now - 50}, "backend": "agy", "model": "flash", "seconds": 10.0, "ok": true}}\n'
    )
    del_file.write_text(del_content)

    al_content = (
        "   \n"
        '{"no_ts": true}\n'
        f'{{"ts": {now - 60}, "tool": "test", "model": "m1", "seconds": 5.0, "ok": false, "error": "timeout"}}\n'
    )
    al_file.write_text(al_content)

    oc_content = (
        '{"ts": null}\n'
        f'{{"ts": {now - 70}, "decision": "allow"}}\n'
        f'{{"ts": {now - 80}, "decision": "invalid_decision"}}\n'
    )
    oc_file.write_text(oc_content)

    report = offload.generate_report(
        delegate_path=del_file,
        ask_local_path=al_file,
        offload_check_path=oc_file,
        days=7,
        now=now,
    )

    # 1 valid delegate + 1 valid ask_local = 2
    assert report["total"]["calls"] == 2
    assert report["total"]["ok"] == 1
    assert report["total"]["failed"] == 1
    assert report["subagents"]["allowed"] == 1
    assert report["subagents"]["denied"] == 0


def test_days_window_filtering(tmp_path: Path):
    del_file = tmp_path / "delegate.jsonl"
    al_file = tmp_path / "empty.jsonl"
    oc_file = tmp_path / "empty_oc.jsonl"

    al_file.write_text("")
    oc_file.write_text("")

    now = 1792940000.0
    day = 86400.0

    lines = [
        {"ts": now - (1 * day), "backend": "agy", "model": "m1", "seconds": 1.0, "ok": True},
        {"ts": now - (5 * day), "backend": "agy", "model": "m1", "seconds": 1.0, "ok": True},
        {"ts": now - (10 * day), "backend": "agy", "model": "m1", "seconds": 1.0, "ok": True},
        {"ts": now - (20 * day), "backend": "agy", "model": "m1", "seconds": 1.0, "ok": True},
    ]
    del_file.write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    # 7-day window -> should capture 1d and 5d = 2 calls
    rep7 = offload.generate_report(delegate_path=del_file, ask_local_path=al_file, offload_check_path=oc_file, days=7, now=now)
    assert rep7["total"]["calls"] == 2

    # 14-day window -> should capture 1d, 5d, 10d = 3 calls
    rep14 = offload.generate_report(delegate_path=del_file, ask_local_path=al_file, offload_check_path=oc_file, days=14, now=now)
    assert rep14["total"]["calls"] == 3

    # 3-day window -> should capture 1d = 1 call
    rep3 = offload.generate_report(delegate_path=del_file, ask_local_path=al_file, offload_check_path=oc_file, days=3, now=now)
    assert rep3["total"]["calls"] == 1


def test_tool_tally_share_and_failures(tmp_path: Path):
    del_file = tmp_path / "delegate.jsonl"
    al_file = tmp_path / "empty.jsonl"
    oc_file = tmp_path / "empty_oc.jsonl"
    al_file.write_text("")
    oc_file.write_text("")

    now = 1792940000.0
    long_error = "a" * 80  # should be truncated to 60

    lines = [
        {
            "ts": now - 10,
            "backend": "agy",
            "model": "gemini-3.8-flash-high",
            "seconds": 20.0,
            "ok": True,
            "tools": {"mcp:jcodemunch": 6, "mcp:jdocmunch": 2, "read_file": 2},
        },
        {
            "ts": now - 20,
            "backend": "agy",
            "model": "gemini-3.8-flash-high",
            "seconds": 5.0,
            "ok": False,
            "error": "status ERROR",
            "tools": {"run_command": 2},
        },
        {
            "ts": now - 30,
            "backend": "agy",
            "model": "gemini-3.8-flash-high",
            "seconds": 4.0,
            "ok": False,
            "error": long_error,
        },
        {
            # Heretic tools should not count toward agy tool tally
            "ts": now - 40,
            "backend": "heretic",
            "model": "heretic",
            "seconds": 1.0,
            "ok": True,
            "tools": {"mcp:ignore": 10},
        },
    ]
    del_file.write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    report = offload.generate_report(delegate_path=del_file, ask_local_path=al_file, offload_check_path=oc_file, days=7, now=now)

    # Tool tally:
    # Call 1: mcp=8 (6+2), shell_file=2
    # Call 2: shell_file=2
    # Total mcp=8, shell_file=4, total=12. Share = 8/12 = 0.6667
    assert report["agy_tools"]["mcp"] == 8
    assert report["agy_tools"]["shell_file"] == 4
    assert report["agy_tools"]["total"] == 12
    assert report["agy_tools"]["mcp_share"] == 0.6667

    # Failures:
    # 2 failures: "status ERROR" (quota exhausted) and long_error
    assert report["agy_failures"]["total"] == 2
    assert report["agy_failures"]["quota_exhausted"] == 1
    assert "status ERROR" in report["agy_failures"]["by_error"]
    assert report["agy_failures"]["by_error"]["status ERROR"] == 1
    # Check truncated error (60 chars)
    truncated_key = "a" * 60
    assert truncated_key in report["agy_failures"]["by_error"]
    assert long_error not in report["agy_failures"]["by_error"]


def test_json_shape_and_cli(tmp_path: Path, capsys):
    del_file = tmp_path / "delegate.jsonl"
    al_file = tmp_path / "ask_local.jsonl"
    oc_file = tmp_path / "offload-check.jsonl"

    now = time.time()

    del_file.write_text(json.dumps({"ts": now - 100, "backend": "agy", "model": "flash", "seconds": 10.0, "ok": True}) + "\n")
    al_file.write_text(json.dumps({"ts": now - 200, "tool": "summarize", "model": "heretic", "seconds": 2.0, "ok": True}) + "\n")
    oc_file.write_text(json.dumps({"ts": now - 300, "decision": "deny", "subagent_type": "swe"}) + "\n")

    # Run via CLI function with --json
    code = offload.main([
        "--delegate", str(del_file),
        "--ask-local", str(al_file),
        "--offload-check", str(oc_file),
        "--days", "7",
        "--json",
    ])
    assert code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert "headline" in data
    assert data["headline"] == "offloaded 2 calls (2 ok) in 7 days; Claude subagents allowed 0, redirected 1"
    assert data["days"] == 7
    assert data["total"]["calls"] == 2
    assert data["total"]["ok"] == 2
    assert data["total"]["failed"] == 0
    assert "by_day" in data
    assert "agy_failures" in data
    assert "agy_tools" in data
    assert "subagents" in data
    assert data["subagents"]["allowed"] == 0
    assert data["subagents"]["denied"] == 1


def test_text_report_formatting(tmp_path: Path, capsys):
    del_file = tmp_path / "delegate.jsonl"
    al_file = tmp_path / "empty.jsonl"
    oc_file = tmp_path / "empty_oc.jsonl"
    al_file.write_text("")
    oc_file.write_text("")

    now = time.time()
    del_file.write_text(json.dumps({"ts": now - 100, "backend": "agy", "model": "flash", "seconds": 10.0, "ok": True}) + "\n")

    code = offload.main([
        "--delegate", str(del_file),
        "--ask-local", str(al_file),
        "--offload-check", str(oc_file),
        "--days", "7",
    ])
    assert code == 0

    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert lines[0] == "offloaded 1 calls (1 ok) in 7 days; Claude subagents allowed 0, redirected 0"
    assert "Antigravity (agy) Tool Tally:" in captured.out
    assert "Antigravity (agy) Failures:" in captured.out
    assert "Claude Subagent Spawns:" in captured.out

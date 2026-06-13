"""Unit tests for the transcript→markdown exporter pure functions
(scripts/memweave/export_transcripts.py). Stdlib-only — no model, runs anywhere.

The exporter's job is to keep the *conversation* (human prompts + assistant prose)
and drop the mechanical traffic (tool_use / tool_result / thinking) and injected
system-reminders — that noise is what tanked the old mempalace mining to ~0 recall.
"""
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts" / "memweave"))

from export_transcripts import (  # noqa: E402
    DEFAULT_WORKSPACE,
    extract_text,
    iter_turns,
    render_markdown,
    strip_system_reminders,
)


def test_default_workspace_not_under_dot_memweave():
    """Regression: memweave's list_memory_files skips any path containing
    '.memweave' in its parts (its internal index dir). A workspace under a
    '.memweave'-named dir silently indexes 0 files. Keep the default clear of it."""
    assert ".memweave" not in DEFAULT_WORKSPACE.parts


def test_extract_text_from_string():
    assert extract_text("hello there") == "hello there"


def test_extract_text_joins_only_text_blocks():
    content = [
        {"type": "thinking", "thinking": "secret internal reasoning"},
        {"type": "text", "text": "first visible"},
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
        {"type": "text", "text": "second visible"},
    ]
    assert extract_text(content) == "first visible\n\nsecond visible"


def test_extract_text_drops_tool_result():
    content = [{"type": "tool_result", "content": "huge tool output \n with secrets"}]
    assert extract_text(content) == ""


def test_extract_text_empty_and_unknown():
    assert extract_text(None) == ""
    assert extract_text([]) == ""
    assert extract_text([{"type": "image"}]) == ""


def test_strip_system_reminders():
    raw = "real question\n<system-reminder>do X always</system-reminder>\nmore text"
    cleaned = strip_system_reminders(raw)
    assert "system-reminder" not in cleaned
    assert "do X always" not in cleaned
    assert "real question" in cleaned
    assert "more text" in cleaned


def test_strip_system_reminders_multiline():
    raw = "keep\n<system-reminder>\nline1\nline2\n</system-reminder>\nalso keep"
    cleaned = strip_system_reminders(raw)
    assert "line1" not in cleaned and "line2" not in cleaned
    assert "keep" in cleaned and "also keep" in cleaned


def _lines(*objs):
    return [json.dumps(o) for o in objs]


def test_iter_turns_keeps_user_and_assistant_text():
    lines = _lines(
        {"type": "queue-operation", "sessionId": "s"},
        {"type": "user", "message": {"role": "user", "content": "what is the plan"}},
        {"type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "thinking", "thinking": "x"},
                        {"type": "text", "text": "the plan is Y"}]}},
        {"type": "user", "message": {"role": "user",
            "content": [{"type": "tool_result", "content": "noise"}]}},
        {"type": "system", "content": "system thing"},
    )
    turns = iter_turns(lines)
    assert turns == [("user", "what is the plan"), ("assistant", "the plan is Y")]


def test_iter_turns_skips_blank_and_bad_json():
    lines = ["", "   ", "{not json", json.dumps(
        {"type": "user", "message": {"role": "user", "content": "real"}})]
    assert iter_turns(lines) == [("user", "real")]


def test_iter_turns_drops_system_reminder_only_user_turn():
    lines = _lines(
        {"type": "user", "message": {"role": "user",
            "content": "<system-reminder>only a reminder</system-reminder>"}},
        {"type": "user", "message": {"role": "user", "content": "genuine ask"}},
    )
    assert iter_turns(lines) == [("user", "genuine ask")]


def test_render_markdown_structure():
    md = render_markdown("abc123", [("user", "q1"), ("assistant", "a1")],
                         project="-opt-proj-Uncle-J-s-Refinery", date_iso="2026-06-12")
    assert "# Session abc123" in md
    assert "-opt-proj-Uncle-J-s-Refinery" in md and "2026-06-12" in md
    assert "## User\n\nq1" in md
    assert "## Assistant\n\na1" in md


def test_render_markdown_empty_turns_is_empty():
    assert render_markdown("x", []) == ""


def test_export_all_projects_covers_every_project_dir(tmp_path):
    """Cross-project widening: export_all_projects must walk every project dir under
    projects_root and export each into one shared store, preserving per-file project
    metadata. Session ids are globally-unique UUIDs, so the flat memory/ dir never collides."""
    from export_transcripts import export_all_projects  # noqa: E402

    proot = tmp_path / "projects"
    specs = [("-proj-alpha", "aaaaaaaa-1111", "the alpha decision rationale "),
             ("-proj-beta", "bbbbbbbb-2222", "the beta decision rationale ")]
    for proj, sid, q in specs:
        d = proot / proj
        d.mkdir(parents=True)
        line = json.dumps({"type": "user", "message": {"role": "user", "content": q * 20}})
        (d / f"{sid}.jsonl").write_text(line + "\n")
    # a non-dir entry under the root must be skipped, not crash
    (proot / "stray-file.txt").write_text("ignore me")

    out = tmp_path / "store"
    written, small, empty, projects = export_all_projects(
        projects_root=proot, out_workspace=out, min_chars=50)

    assert projects == 2
    assert written == 2
    mem = out / "memory"
    assert (mem / "aaaaaaaa-1111.md").exists()
    assert (mem / "bbbbbbbb-2222.md").exists()
    assert "-proj-alpha" in (mem / "aaaaaaaa-1111.md").read_text()
    assert "-proj-beta" in (mem / "bbbbbbbb-2222.md").read_text()

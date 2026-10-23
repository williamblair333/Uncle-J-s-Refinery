import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("waiting_sweep", REPO / "scripts" / "waiting_sweep.py")
ws = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ws)


def test_bold_label_counts_as_waiting_heading():
    text = ("## 2026-10-22 — session end\n\n**Most important:** keep Ollama.\n\n**Open / next:**\n"
            "- fix grep-guard\n- lineup\n\n## 2026-10-21 — older\n**Open / next:**\n- stale item\n")
    assert ws.waiting_sections(text, 10) == [("Open / next", ["- fix grep-guard", "- lineup"])]


def test_heading_sections_unchanged():
    text = "## Waiting on Bill\n1. Etsy app\n## Done\n- x\n### Next session\n- 3MF export\n"
    assert [h for h, _ in ws.waiting_sections(text, 10)] == ["Waiting on Bill", "Next session"]


def test_roadmap_items_skip_done_and_other_sections():
    text = (
        "## In Progress\n- **Live demo** (opened)\n"
        "## Planned\n- **Ship dcup** (opened)\n  - **nested** ignored\n"
        "- **[DONE 2026-10-22] grep fix** — done\n- **~~old~~**\n- **Phase 2** ✅ DONE\n"
        "- **Local model lineup: fewest models.**\n"
        "## Recently completed\n- **Shipped thing**\n"
    )
    assert ws.roadmap_items(text) == ["Live demo", "Ship dcup", "Local model lineup: fewest models"]


def test_memory_items_reads_description(tmp_path):
    mem = tmp_path / "-opt-proj-X" / "memory"
    mem.mkdir(parents=True)
    (mem / "project_anatomy-lab.md").write_text('---\nname: a\ndescription: "top priority figures"\n---\nbody\n')
    (mem / "feedback_x.md").write_text("---\ndescription: not a project\n---\n")
    assert ws.memory_items(str(tmp_path), 0) == [("-opt-proj-X", "anatomy-lab", "top priority figures")]


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def test_main_flags_repo_without_handoff_and_lists_roadmap(tmp_path):
    root = tmp_path / "proj"
    a, b = root / "nohandoff", root / "withroadmap"
    for r in (a, b):
        r.mkdir(parents=True)
        _git(r, "init", "-q", "-b", "main")
    (a / "f.txt").write_text("x")
    (b / "ROADMAP.md").write_text("## Planned\n- **Image models**\n")
    (b / "HANDOFF.md").write_text("# H\n")
    for r in (a, b):
        _git(r, "add", "-A")
        _git(r, "commit", "-qm", "init")
        _git(r, "remote", "add", "origin", "http://example.invalid/x.git")
    p = subprocess.run([sys.executable, str(REPO / "scripts" / "waiting_sweep.py"), "--root", str(root),
                        "--memory-root", str(tmp_path / "nomem")], capture_output=True, text=True, check=True)
    assert "## nohandoff  [no HANDOFF.md" in p.stdout
    assert "### ROADMAP open items (1)\n- Image models" in p.stdout

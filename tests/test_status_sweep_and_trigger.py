import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sweep = load("waiting_sweep", "scripts/waiting_sweep.py")
trigger = load("skill_name_trigger", "features/prompt-triggers/skill_name_trigger.py")

SKILLS = {"just-do-it", "pre-mortem", "judge", "grill-me", "session-status-briefing"}


def test_hyphenated_name_triggers():
    assert trigger.named_skills("then just-do-it all the things", SKILLS) == ["just-do-it"]


def test_slash_form_triggers_single_word():
    assert trigger.named_skills("run /judge on it", SKILLS) == ["judge"]


def test_bare_single_word_does_not_trigger():
    assert trigger.named_skills("you be the judge", SKILLS) == []


def test_name_inside_path_does_not_trigger():
    assert trigger.named_skills("see global-skills/pre-mortem/SKILL.md", SKILLS) == []


def test_multiple_names():
    assert trigger.named_skills("pre-mortem then /grill-me", SKILLS) == ["grill-me", "pre-mortem"]


def test_hook_output_shape(tmp_path):
    skill = tmp_path / ".claude" / "skills" / "just-do-it"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: just-do-it\n---\n")
    p = subprocess.run([sys.executable, str(ROOT / "features/prompt-triggers/skill_name_trigger.py")],
                       input=json.dumps({"prompt": "just-do-it now"}), capture_output=True, text=True,
                       env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})
    out = json.loads(p.stdout)
    assert "just-do-it" in out["hookSpecificOutput"]["additionalContext"]


def test_hook_silent_on_garbage():
    p = subprocess.run([sys.executable, str(ROOT / "features/prompt-triggers/skill_name_trigger.py")],
                       input="not json", capture_output=True, text=True)
    assert p.returncode == 0 and p.stdout == ""


HANDOFF = """# Handoff
## 2026-10-21 — current
### Waiting on Bill
1. Etsy app
### Next session
Build price
## 2026-05-01 — old entry
### Next action
Old work
## Next session
Duplicate heading, older
"""


def test_waiting_sections_keeps_recent_and_drops_stale():
    got = sweep.waiting_sections(HANDOFF, 10, "2026-08-01")
    heads = [h for h, _ in got]
    assert heads == ["Waiting on Bill", "Next session"]
    assert got[1][1] == ["Build price"]


def test_waiting_sections_truncates():
    text = "## Waiting\n" + "\n".join(f"- item {i}" for i in range(20))
    (_, body), = sweep.waiting_sections(text, 3)
    assert len(body) == 4 and "17 more lines" in body[-1]

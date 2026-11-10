"""Tests for scripts/tools.py: the tool standard lint, the catalog and the global justfile."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tools_mod", REPO / "scripts" / "tools.py")
tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools)

needs_just = pytest.mark.skipif(shutil.which("just") is None, reason="just not installed")

GOOD_SCRIPT = """#!/usr/bin/env bash
# fix-thing.sh - fix the thing that breaks after reboot
#
# Full write-up: fix-thing.md
case "$1" in
  --check) echo ok ;; --fix) echo fixed ;; -n|--dry-run) echo dry ;;
  --json) echo '{}' ;; -h|--help) echo usage ;; -V|--version) echo 1.0.0 ;;
esac
cfg="$HOME/.config/thing"
"""


def make_project(root: Path, name: str, justfile: str, files: dict | None = None) -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    (proj / "justfile").write_text(justfile)
    for rel, text in (files or {}).items():
        path = proj / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o755)
    return proj


TOOL_JUSTFILE = """# fix the thing (--check, --fix)
[group('tools')]
fix-thing *args:
    ./fix-thing.sh {{args}}

# say hi
hello:
    @echo hi from $(basename "$PWD")
"""


# ------------------------------------------------------------------ lint ----

def test_compliant_script_has_no_errors(tmp_path):
    proj = make_project(tmp_path, "p", TOOL_JUSTFILE, {"fix-thing.sh": GOOD_SCRIPT, "tests/test_fix_thing.py": ""})
    problems = tools.lint_script(proj / "fix-thing.sh", proj)
    assert problems == []


def test_missing_flags_and_test_are_errors(tmp_path):
    proj = make_project(tmp_path, "p", TOOL_JUSTFILE, {"fix-thing.sh": "#!/bin/sh\necho hi\n"})
    codes = {p["code"] for p in tools.lint_script(proj / "fix-thing.sh", proj) if p["level"] == "E"}
    assert codes == {"header", "help", "version", "dry-run", "check", "test"}


def test_hard_coded_home_is_an_error_but_not_in_comments(tmp_path):
    body = GOOD_SCRIPT + "# see /home/bill/notes\nlog=/home/bill/thing.log\n"
    proj = make_project(tmp_path, "p", TOOL_JUSTFILE, {"fix-thing.sh": body, "tests/test_fix_thing.py": ""})
    homes = [p for p in tools.lint_script(proj / "fix-thing.sh", proj) if p["code"] == "home-path"]
    assert len(homes) == 1 and homes[0]["level"] == "E"


def test_uid_and_proj_root_are_warnings(tmp_path):
    body = GOOD_SCRIPT + 'test "$(id -u)" = 1000\nd=/opt/proj/x\nr="${PROJ_ROOT:-/opt/proj}"\n'
    proj = make_project(tmp_path, "p", TOOL_JUSTFILE, {"fix-thing.sh": body, "tests/test_fix_thing.py": ""})
    found = {(p["code"], p["level"]) for p in tools.lint_script(proj / "fix-thing.sh", proj)}
    assert found == {("uid", "W"), ("proj-root", "W")}


def test_read_only_tools_need_no_dry_run_or_check(tmp_path):
    body = ('"""miner.py - list things\n\nread-only: changes nothing.\n"""\nimport argparse\n'
            'p = argparse.ArgumentParser()\np.add_argument("--version")\np.add_argument("--json")\n')
    proj = make_project(tmp_path, "p", TOOL_JUSTFILE, {"miner.py": body, "tests/test_miner.py": ""})
    assert tools.lint_script(proj / "miner.py", proj) == []


def test_flags_named_only_in_comments_do_not_count(tmp_path):
    body = "#!/bin/sh\n# fake.sh - claims flags in comments only\n# --help --version --dry-run --check --test\necho hi\n"
    proj = make_project(tmp_path, "p", TOOL_JUSTFILE, {"fake.sh": body})
    codes = {p["code"] for p in tools.lint_script(proj / "fake.sh", proj) if p["level"] == "E"}
    assert codes == {"help", "version", "dry-run", "check", "test"}


def test_test_mode_counts_as_a_test(tmp_path):
    body = GOOD_SCRIPT + "  --test) run_tests ;;\n"
    proj = make_project(tmp_path, "p", TOOL_JUSTFILE, {"fix-thing.sh": body})
    assert all(p["code"] != "test" for p in tools.lint_script(proj / "fix-thing.sh", proj))


@needs_just
def test_lint_repo_finds_the_tool_and_its_script(tmp_path):
    proj = make_project(tmp_path, "p", TOOL_JUSTFILE, {"fix-thing.sh": GOOD_SCRIPT, "tests/test_fix_thing.py": ""})
    rows = tools.lint_repo(proj)
    assert [(r["recipe"], r["tool"], r["script"]) for r in rows] == [("fix-thing", True, "fix-thing.sh")]
    assert tools.main(["lint", str(proj)]) == 0


@needs_just
def test_lint_repo_resolves_justfile_directory_paths(tmp_path):
    jf = """# run x
[group('tools')]
x *args:
    cd "{{invocation_directory()}}" && python3 "{{justfile_directory()}}/scripts/x.py" {{args}}
"""
    proj = make_project(tmp_path, "p", jf, {"scripts/x.py": "", ".venv/bin/python": ""})
    rows = tools.lint_repo(proj)
    assert rows[0]["script"] == "scripts/x.py"


@needs_just
def test_failing_tool_exits_1_and_all_reports_other_recipes(tmp_path):
    jf = TOOL_JUSTFILE + "\n# other\nother:\n    ./other.sh\n"
    proj = make_project(tmp_path, "p", jf, {"fix-thing.sh": "#!/bin/sh\n", "other.sh": "#!/bin/sh\n"})
    assert tools.main(["lint", str(proj)]) == 1
    rows = tools.lint_repo(proj, all_recipes=True)
    assert {r["recipe"]: r["tool"] for r in rows} == {"fix-thing": True, "other": False}


def test_declared_tools_that_parse_to_none_is_an_error(tmp_path, monkeypatch):
    """If just's dump format changes, a silent '0 tools, 0 failing' must not read as green."""
    proj = make_project(tmp_path, "p", TOOL_JUSTFILE, {"fix-thing.sh": GOOD_SCRIPT})
    monkeypatch.setattr(tools, "dump", lambda _jf: {"recipes": {"fix-thing": {"doc": "x", "body": []}}})
    with pytest.raises(tools.ToolsError, match="changed format"):
        tools.lint_repo(proj)
    assert tools.main(["lint", str(proj)]) == 2


# ------------------------------------------------------- catalog / sync ----

@needs_just
def test_catalog_lists_documented_recipes_and_filters(tmp_path):
    make_project(tmp_path, "alpha", TOOL_JUSTFILE + "\nhidden:\n    true\n")
    make_project(tmp_path, "beta", "# back up the vault\nbackup:\n    true\n")
    rows, broken = tools.catalog(tmp_path, all_recipes=True)
    assert broken == []
    assert {(r["project"], r["recipe"], r["tool"]) for r in rows} == {
        ("alpha", "fix-thing", True), ("alpha", "hello", False), ("beta", "backup", False)}
    only_tools, _ = tools.catalog(tmp_path, all_recipes=False)
    assert [r["recipe"] for r in only_tools] == ["fix-thing"]
    backups, _ = tools.catalog(tmp_path, all_recipes=True, term="VAULT")
    assert [r["project"] for r in backups] == ["beta"]


@needs_just
def test_render_global_skips_unsafe_and_broken_projects(tmp_path):
    make_project(tmp_path, "good", TOOL_JUSTFILE)
    make_project(tmp_path, "loads-a-command", "x := `date`\n# hi\nhi:\n    true\n")
    make_project(tmp_path, "broken", "this is : not ( a justfile\n")
    make_project(tmp_path, "has.dot", "# hi\nhi:\n    true\n")
    make_project(tmp_path, "_archive", "# hi\nhi:\n    true\n")
    content, skipped = tools.render_global(tmp_path)
    mods = [line.split()[1] for line in content.splitlines() if line.startswith("mod ")]
    assert mods == ["good"]
    assert any(s.startswith("loads-a-command") for s in skipped)
    assert any(s.startswith("broken") for s in skipped)
    assert any(s.startswith("has.dot") for s in skipped)
    assert tools.rejection(content) is None


@needs_just
def test_sync_writes_checks_and_refuses_foreign_files(tmp_path, monkeypatch, capsys):
    root = tmp_path / "proj"
    make_project(root, "good", TOOL_JUSTFILE)
    target = tmp_path / "config" / "just" / "justfile"
    monkeypatch.setenv("PROJ_ROOT", str(root))
    monkeypatch.setenv("GLOBAL_JUSTFILE", str(target))

    assert tools.main(["sync", "--check"]) == 1          # missing
    assert tools.main(["sync", "--dry-run"]) == 0 and not target.exists()
    assert tools.main(["sync"]) == 0 and target.is_file()
    assert tools.main(["sync", "--check"]) == 0          # current
    make_project(root, "newer", "# hi\nhi:\n    true\n")
    assert tools.main(["sync", "--check"]) == 1          # stale

    target.write_text("# my own global justfile\n")
    assert tools.main(["sync"]) == 2                     # not ours: left alone
    assert target.read_text() == "# my own global justfile\n"
    assert tools.main(["sync", "--force"]) == 0
    capsys.readouterr()
    assert tools.main(["sync", "--check", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "current"


@needs_just
def test_generated_file_runs_a_project_recipe_from_another_folder(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    make_project(root, "good", TOOL_JUSTFILE)
    target = tmp_path / "global"
    monkeypatch.setenv("PROJ_ROOT", str(root))
    monkeypatch.setenv("GLOBAL_JUSTFILE", str(target))
    assert tools.main(["sync"]) == 0
    out = subprocess.run(["just", "--justfile", str(target), "good", "hello"],
                         cwd=tmp_path, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "hi from good"   # runs in the project's own folder


@needs_just
def test_justfile_directory_is_flagged_and_source_directory_works_under_g(tmp_path, monkeypatch):
    """Under `just -g`, justfile_directory() is the global file's folder; source_directory() is the project's."""
    root = tmp_path / "proj"
    bad = """# run x
[group('tools')]
x:
    python3 "{{justfile_directory()}}/x.py"
"""
    good = """# run x
[group('tools')]
x:
    @python3 "{{source_directory()}}/x.py"
"""
    make_project(root, "bad", bad, {"x.py": "print('ran bad')\n"})
    make_project(root, "good", good, {"x.py": "print('ran good')\n"})
    assert "justfile-dir" in {p["code"] for p in tools.lint_repo(root / "bad")[0]["problems"]}
    assert "justfile-dir" not in {p["code"] for p in tools.lint_repo(root / "good")[0]["problems"]}

    target = tmp_path / "global"
    monkeypatch.setenv("PROJ_ROOT", str(root))
    monkeypatch.setenv("GLOBAL_JUSTFILE", str(target))
    assert tools.main(["sync"]) == 0
    out = subprocess.run(["just", "--justfile", str(target), "good", "x"],
                         cwd=tmp_path, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "ran good"


@needs_just
def test_refinery_tools_meet_the_standard():
    """The Refinery's own tools group passes its own lint."""
    rows = tools.lint_repo(REPO)
    failing = {r["recipe"]: r["problems"] for r in rows
               if r["tool"] and any(p["level"] == "E" for p in r["problems"])}
    assert {r["recipe"] for r in rows if r["tool"]} >= {"tools", "tool-mine", "inbox"}
    assert failing == {}


def test_template_passes_everything_but_the_test_rule(tmp_path):
    template = REPO / "features" / "tool-recipes" / "template.sh"
    codes = {p["code"] for p in tools.lint_script(template, tmp_path)}
    assert codes == {"test"}


def test_a_bare_word_or_nothing_searches_the_catalog(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setenv("PROJ_ROOT", str(tmp_path))
    monkeypatch.setattr(tools, "catalog", lambda root, all_recipes, term: (seen.append(term), ([], []))[1])
    assert tools.main(["backup"]) == 0
    assert tools.main([]) == 0
    assert seen == ["backup", ""]

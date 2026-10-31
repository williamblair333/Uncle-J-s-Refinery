import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location(
    "standards_check", REPO / "features" / "product-quality" / "standards_check.py")
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)
HOOK = REPO / "features" / "product-quality" / "hooks" / "product-md-check.sh"

GOOD = """# Standards — demo

What a senior practitioner would already have in place.

```yaml
phase: early QA
standards:
  - id: bench-per-system
    area: QA
    bar: Every system has a bench suite that builds its own state in under 60 s
    why: fixes are proven on forced events, not live luck
    status: open
    evidence: no bench for siege or diplomacy
  - id: ci-on-push
    area: release
    bar: Every push runs the full suite
    why: regressions are caught before merge
    status: done
    evidence: ci.yml
  - id: one-command-run
    area: release
    bar: One command starts everything
    why: anyone can reproduce a run
    status: partial
    evidence: just up
  - id: crash-capture
    area: QA
    bar: Every crash leaves a dump and a log
    why: no crash is diagnosed from memory
    status: open
    evidence: dumps are not collected
```
"""


def project(tmp_path, text=GOOD, justfile="up:\n    echo up\n", files=("ci.yml",)):
    (tmp_path / "STANDARDS.md").write_text(text)
    if justfile is not None:
        (tmp_path / "justfile").write_text(justfile)
    for f in files:
        (tmp_path / f).write_text("x")
    return tmp_path


def test_load_returns_phase_and_items_in_rank_order(tmp_path):
    data = sc.load(project(tmp_path))
    assert data["phase"] == "early QA"
    assert [s["id"] for s in data["standards"]] == ["bench-per-system", "ci-on-push",
                                                    "one-command-run", "crash-capture"]


def test_valid_file_has_no_problems(tmp_path):
    p = project(tmp_path)
    assert sc.validate(sc.load(p), p) == []


def test_done_item_with_missing_evidence_is_a_false_claim(tmp_path):
    p = project(tmp_path, files=())  # ci.yml absent
    problems = sc.validate(sc.load(p), p)
    assert any("ci-on-push" in x and "false claim" in x for x in problems)


def test_partial_item_naming_a_missing_just_recipe_is_a_false_claim(tmp_path):
    p = project(tmp_path, justfile="down:\n    echo down\n")
    problems = sc.validate(sc.load(p), p)
    assert any("one-command-run" in x and "false claim" in x for x in problems)


def test_open_item_evidence_is_free_text(tmp_path):
    p = project(tmp_path)
    assert not any("bench-per-system" in x for x in sc.validate(sc.load(p), p))


@pytest.mark.parametrize("field", ["id", "bar", "status"])
def test_missing_required_field_is_named(tmp_path, field):
    text = GOOD.replace(f"    {field}: " if field != "id" else "  - id: crash-capture\n",
                        "    x_removed: " if field != "id" else "  - x_removed: 1\n", 1)
    p = project(tmp_path, text=text)
    assert any(field in x for x in sc.validate(sc.load(p), p))


def test_unknown_status_is_a_problem(tmp_path):
    p = project(tmp_path, text=GOOD.replace("status: open", "status: wip", 1))
    assert any("wip" in x for x in sc.validate(sc.load(p), p))


IDEAS = """  - id: pareto-failures
    idea: Classify failures by cause and fix the biggest class first
    from: manufacturing
    test: tag last week's failures from the log
    kill: causes spread too evenly to rank
    status: untested
"""


def _ideas_text(ideas=IDEAS):
    head, sep, tail = GOOD.rpartition("```\n")
    return head + "ideas:\n" + ideas + sep + tail


def test_valid_ideas_list_has_no_problems(tmp_path):
    p = project(tmp_path, text=_ideas_text())
    assert sc.validate(sc.load(p), p) == []


def test_load_returns_ideas(tmp_path):
    data = sc.load(project(tmp_path, text=_ideas_text()))
    assert [i["id"] for i in data["ideas"]] == ["pareto-failures"]


def test_file_without_ideas_loads_empty_ideas(tmp_path):
    assert sc.load(project(tmp_path))["ideas"] == []


@pytest.mark.parametrize("field", ["idea", "from", "test", "kill"])
def test_idea_missing_hypothesis_field_is_named(tmp_path, field):
    ideas = "\n".join(l for l in IDEAS.splitlines() if not l.strip().startswith(f"{field}:")) + "\n"
    p = project(tmp_path, text=_ideas_text(ideas))
    problems = sc.validate(sc.load(p), p)
    assert any("pareto-failures" in x and f"'{field}'" in x for x in problems)


def test_idea_unknown_status_is_a_problem(tmp_path):
    p = project(tmp_path, text=_ideas_text(IDEAS.replace("untested", "maybe")))
    assert any("maybe" in x for x in sc.validate(sc.load(p), p))


def test_ideas_not_a_list_is_a_problem(tmp_path):
    p = project(tmp_path, text=_ideas_text("  pareto: yes\n"))
    assert any("ideas" in x for x in sc.validate(sc.load(p), p))


def test_summary_counts_untested_ideas(tmp_path):
    out = sc.summary(project(tmp_path, text=_ideas_text()))
    assert "1 idea untested" in out.splitlines()[0]


def test_summary_without_ideas_says_nothing_about_ideas(tmp_path):
    assert "idea" not in sc.summary(project(tmp_path)).splitlines()[0]


def test_summary_lists_open_and_partial_gaps_in_rank_order_capped(tmp_path):
    out = sc.summary(project(tmp_path), top=2)
    lines = out.splitlines()
    assert "3 open of 4" in lines[0] and "early QA" in lines[0]
    assert "bench-per-system" in out and "one-command-run" in out
    assert "crash-capture" not in out  # rank 3 of the gaps, cut by top=2
    assert out.index("bench-per-system") < out.index("one-command-run")


def test_summary_puts_false_claims_first(tmp_path):
    out = sc.summary(project(tmp_path, files=()), top=5)
    assert out.splitlines()[0].startswith("standards:") and "false claim" in out.splitlines()[0]


def test_summary_without_file_points_at_the_skill(tmp_path):
    out = sc.summary(tmp_path)
    assert "no STANDARDS.md" in out and "expert-bar" in out


def test_summary_with_unparseable_yaml_is_one_line(tmp_path):
    out = sc.summary(project(tmp_path, text="```yaml\nstandards: [\n```\n"))
    assert len(out.splitlines()) == 1 and "cannot parse" in out


def test_summary_without_pyyaml_degrades_to_one_line(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "yaml", None)
    out = sc.summary(project(tmp_path))
    assert len(out.splitlines()) == 1 and "PyYAML" in out


def test_check_cli_exits_nonzero_on_problems(tmp_path):
    p = project(tmp_path, files=())
    r = subprocess.run([sys.executable, str(REPO / "features/product-quality/standards_check.py"),
                        "--check", str(p)], capture_output=True, text=True)
    assert r.returncode == 1 and "false claim" in r.stdout + r.stderr


def _git_project(tmp_path, with_standards, with_product=True):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    if with_product:
        (tmp_path / "PRODUCT.md").write_text("# p\n")
    if with_standards:
        project(tmp_path)
    return tmp_path


def test_session_start_hook_prints_gaps_and_never_fails(tmp_path):
    p = _git_project(tmp_path, with_standards=True)
    r = subprocess.run(["bash", str(HOOK)], cwd=p, capture_output=True, text=True)
    assert r.returncode == 0 and "bench-per-system" in r.stdout


def test_session_start_hook_prints_gaps_without_product_md(tmp_path):
    # mtw2 (2026-10-31): STANDARDS.md but no PRODUCT.md; its gaps must still open the session
    p = _git_project(tmp_path, with_standards=True, with_product=False)
    r = subprocess.run(["bash", str(HOOK)], cwd=p, capture_output=True, text=True)
    assert r.returncode == 0 and "product-brief" in r.stdout and "bench-per-system" in r.stdout


def test_session_start_hook_nudges_when_standards_missing(tmp_path):
    p = _git_project(tmp_path, with_standards=False)
    r = subprocess.run(["bash", str(HOOK)], cwd=p, capture_output=True, text=True)
    assert r.returncode == 0 and "expert-bar" in r.stdout

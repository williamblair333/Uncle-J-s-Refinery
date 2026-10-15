"""Tests for scripts/gen-skills-reference.py (builds docs/SKILLS.md)."""
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("gen_skills_reference", REPO / "scripts" / "gen-skills-reference.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def skill(root: Path, name: str, description: str, body: str = "Do the thing.\n", extra: str = "") -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n{extra}---\n\n{body}")
    return d


def make_env(tmp_path: Path):
    repo, home = tmp_path / "repo", tmp_path / "home"
    (repo / "global-skills").mkdir(parents=True)
    (repo / "global-workflows").mkdir()
    (home / ".claude" / "skills").mkdir(parents=True)
    return repo, home


def render(repo, home, host=False):
    return gen.render(gen.collect(repo, home, host=host), host=host)


def row_for(md: str, name: str) -> str:
    rows = [l for l in md.splitlines() if l.startswith(f"| `{name}` |")]
    assert len(rows) == 1, f"expected one row for {name}, got {rows}"
    return rows[0]


def test_repo_skill_listed_with_first_sentence_purpose(tmp_path):
    repo, home = make_env(tmp_path)
    skill(repo / "global-skills", "alpha", "Does alpha things across the repo. Use when alpha is needed.")
    row = row_for(render(repo, home), "alpha")
    assert "Does alpha things across the repo." in row
    assert "Use when alpha" not in row


def test_too_short_first_sentence_takes_the_next(tmp_path):
    repo, home = make_env(tmp_path)
    skill(repo / "global-skills", "wait-what", "\"Stop. That last message did not land: re-pitch it.\"")
    assert "Stop. That last message did not land" in row_for(render(repo, home), "wait-what")


def test_vendored_skill_shows_upstream(tmp_path):
    repo, home = make_env(tmp_path)
    d = skill(repo / "global-skills", "teach", "Teach the user.")
    (d / "UPSTREAM").write_text("Vendored from https://github.com/mattpocock/skills\nCommit: 49dd158\n")
    md = render(repo, home)
    assert "mattpocock/skills" in row_for(md, "teach")


def test_user_only_invocation(tmp_path):
    repo, home = make_env(tmp_path)
    skill(repo / "global-skills", "retro", "Run a retro.", extra="disable-model-invocation: true\n")
    skill(repo / "global-skills", "auto", "Fires itself.")
    md = render(repo, home)
    assert "| you |" in row_for(md, "retro")
    assert "| auto |" in row_for(md, "auto")


def test_portability_classification(tmp_path):
    repo, home = make_env(tmp_path)
    skill(repo / "global-skills", "plain", "Plain.", body="Write a file.\n")
    skill(repo / "global-skills", "claudey", "Claude.", body="Call AskUserQuestion with the options.\n")
    skill(repo / "global-skills", "stacky", "Stack.", body="Run jcodemunch search_symbols first.\n")
    md = render(repo, home)
    assert "any agent" in row_for(md, "plain")
    assert "Claude Code" in row_for(md, "claudey")
    assert "Refinery stack" in row_for(md, "stacky")


def test_local_only_skill_flagged_and_symlinked_one_not(tmp_path):
    repo, home = make_env(tmp_path)
    src = skill(repo / "global-skills", "linked", "Linked.")
    (home / ".claude" / "skills" / "linked").symlink_to(src)
    skill(home / ".claude" / "skills", "orphan", "Only here.")
    md = render(repo, home, host=True)
    assert "NOT BACKED UP" in row_for(md, "orphan")
    assert md.count("`linked`") == 1  # listed once, under the repo section


def test_local_copy_of_repo_skill_is_not_flagged(tmp_path):
    repo, home = make_env(tmp_path)
    skill(repo / "features" / "dreaming" / "skills", "dream", "Dream.")
    skill(home / ".claude" / "skills", "dream", "Dream.")
    md = render(repo, home, host=True)
    assert "NOT BACKED UP" not in md


def test_plugin_skills_listed_with_namespace(tmp_path):
    repo, home = make_env(tmp_path)
    install = home / ".claude" / "plugins" / "cache" / "mk" / "superpowers" / "1.0.0"
    skill(install / "skills", "brainstorming", "Brainstorm first.")
    reg = {"version": 2, "plugins": {"superpowers@mk": [{"installPath": str(install), "version": "1.0.0"}]}}
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps(reg))
    md = render(repo, home, host=True)
    assert "superpowers 1.0.0" in row_for(md, "superpowers:brainstorming")


def test_workflows_listed(tmp_path):
    repo, home = make_env(tmp_path)
    (repo / "global-workflows" / "adversarial-review.js").write_text("// wf\n")
    (repo / "global-workflows" / "adversarial-review.md").write_text(
        "---\nname: adversarial-review\ndescription: Hostile review. Two rounds.\n---\n")
    md = render(repo, home)
    assert "Hostile review." in row_for(md, "adversarial-review")


def test_pipes_escaped_and_long_purpose_truncated(tmp_path):
    repo, home = make_env(tmp_path)
    skill(repo / "global-skills", "pipey", "Choose a|b " + "x" * 300)
    row = row_for(render(repo, home), "pipey")
    assert "a\\|b" in row
    assert "…" in row


def test_output_is_deterministic_and_check_mode(tmp_path):
    repo, home = make_env(tmp_path)
    skill(repo / "global-skills", "alpha", "Alpha.")
    out = tmp_path / "SKILLS.md"
    assert gen.main(["--repo", str(repo), "--home", str(home), "--output", str(out)]) == 0
    first = out.read_text()
    assert gen.main(["--repo", str(repo), "--home", str(home), "--output", str(out), "--check"]) == 0
    skill(repo / "global-skills", "beta", "Beta.")
    assert gen.main(["--repo", str(repo), "--home", str(home), "--output", str(out), "--check"]) == 1
    assert out.read_text() == first  # --check never writes


def test_committed_file_ignores_host_state(tmp_path):
    """Plugins and local-only skills differ per machine; they must not make --check flap."""
    repo, home = make_env(tmp_path)
    skill(repo / "global-skills", "alpha", "Alpha does things across the repo.")
    out = tmp_path / "SKILLS.md"
    gen.main(["--repo", str(repo), "--home", str(home), "--output", str(out)])
    skill(home / ".claude" / "skills", "orphan", "Only on this host.")
    install = home / ".claude" / "plugins" / "cache" / "mk" / "p" / "2.0.0"
    skill(install / "skills", "s", "Plugin skill.")
    reg = {"plugins": {"p@mk": [{"installPath": str(install), "version": "2.0.0"}]}}
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps(reg))
    assert gen.main(["--repo", str(repo), "--home", str(home), "--output", str(out), "--check"]) == 0
    assert "orphan" not in out.read_text()


def test_host_mode_prints_and_never_writes(tmp_path, capsys):
    repo, home = make_env(tmp_path)
    skill(home / ".claude" / "skills", "orphan", "Only on this host.")
    out = tmp_path / "SKILLS.md"
    assert gen.main(["--repo", str(repo), "--home", str(home), "--output", str(out), "--host"]) == 0
    assert "NOT BACKED UP" in capsys.readouterr().out
    assert not out.exists()


# ── scripts/skill-link.sh: ~/.agents/skills ownership rules ──────────────────

def run_skill_link(home: Path):
    import os
    import subprocess
    env = dict(os.environ, HOME=str(home))
    return subprocess.run(["bash", str(REPO / "scripts" / "skill-link.sh"), "link"],
                          env=env, capture_output=True, text=True)


def test_skill_link_agents_respects_foreign_entries(tmp_path):
    home = tmp_path / "home"
    agents = home / ".agents" / "skills"
    agents.mkdir(parents=True)
    (agents / "teach").mkdir()                                   # another tool's real dir
    (agents / "teach" / "SKILL.md").write_text("theirs")
    elsewhere = tmp_path / "my-handoff"
    elsewhere.mkdir()
    (agents / "handoff").symlink_to(elsewhere)                   # a foreign symlink
    (agents / "gone").symlink_to(REPO / "global-skills" / "gone-skill-xyz")  # our dangling link
    (agents / "foreign-dangling").symlink_to(tmp_path / "nowhere")

    r = run_skill_link(home)
    assert r.returncode == 0, r.stderr
    assert (agents / "teach" / "SKILL.md").read_text() == "theirs"
    assert (agents / "handoff").resolve() == elsewhere.resolve()
    assert not (agents / "gone").is_symlink()
    assert (agents / "foreign-dangling").is_symlink()
    assert (agents / "grilling" / "SKILL.md").is_file()          # ours got linked
    first = sorted((p.name, str(p.readlink()) if p.is_symlink() else "dir") for p in agents.iterdir())
    run_skill_link(home)
    second = sorted((p.name, str(p.readlink()) if p.is_symlink() else "dir") for p in agents.iterdir())
    assert first == second

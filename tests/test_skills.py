"""Regression tests for global-skills SKILL.md files.

Static validation only — no API calls, no model inference.
Catches the most common skill regressions:
- Missing frontmatter
- Required fields absent
- name field doesn't match directory name
- prerequisites.skills references a non-existent skill directory
"""
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
GLOBAL_SKILLS = REPO_ROOT / "global-skills"

VALID_CATEGORIES = {
    "security",
    "review",
    "memory",
    "git",
    "analysis",
    "infrastructure",
    "utility",
}

VALID_PLATFORMS = {"linux", "macos", "windows"}


def skill_dirs():
    return sorted(p for p in GLOBAL_SKILLS.iterdir() if p.is_dir())


def parse_frontmatter(skill_file: Path):
    """Extract and parse YAML frontmatter from a SKILL.md.

    Returns (frontmatter_dict, body_text) or raises ValueError.
    Tolerates a leading blank line before the opening ---.
    """
    text = skill_file.read_text().lstrip("\n")
    if not text.startswith("---"):
        raise ValueError("no frontmatter opening '---'")
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError("no frontmatter closing '---'")
    fm_text = text[3:end].strip()
    body = text[end + 4:]
    return yaml.safe_load(fm_text) or {}, body


# ── parametrize over every skill directory ────────────────────────────────────

@pytest.mark.parametrize("skill_dir", skill_dirs(), ids=lambda p: p.name)
class TestSkillFrontmatter:

    def test_skill_md_exists(self, skill_dir):
        assert (skill_dir / "SKILL.md").exists(), "SKILL.md missing"

    def test_frontmatter_is_valid_yaml(self, skill_dir):
        skill_file = skill_dir / "SKILL.md"
        try:
            parse_frontmatter(skill_file)
        except ValueError as e:
            pytest.fail(str(e))
        except yaml.YAMLError as e:
            pytest.fail(f"YAML parse error: {e}")

    def test_required_field_name(self, skill_dir):
        fm, _ = parse_frontmatter(skill_dir / "SKILL.md")
        assert "name" in fm, "missing required field: name"
        assert isinstance(fm["name"], str) and fm["name"].strip(), "name must be non-empty string"

    def test_required_field_description(self, skill_dir):
        fm, _ = parse_frontmatter(skill_dir / "SKILL.md")
        assert "description" in fm, "missing required field: description"
        assert isinstance(fm["description"], str) and fm["description"].strip(), \
            "description must be non-empty string"

    def test_name_matches_directory(self, skill_dir):
        fm, _ = parse_frontmatter(skill_dir / "SKILL.md")
        if "name" not in fm:
            pytest.skip("name field absent — covered by test_required_field_name")
        assert fm["name"] == skill_dir.name, \
            f"name '{fm['name']}' doesn't match directory '{skill_dir.name}'"

    def test_category_is_valid_if_present(self, skill_dir):
        fm, _ = parse_frontmatter(skill_dir / "SKILL.md")
        if "category" not in fm:
            return
        assert fm["category"] in VALID_CATEGORIES, \
            f"unknown category '{fm['category']}'; valid: {sorted(VALID_CATEGORIES)}"

    def test_platforms_are_valid_if_present(self, skill_dir):
        fm, _ = parse_frontmatter(skill_dir / "SKILL.md")
        if "platforms" not in fm:
            return
        assert isinstance(fm["platforms"], list), "platforms must be a list"
        for p in fm["platforms"]:
            assert p in VALID_PLATFORMS, \
                f"unknown platform '{p}'; valid: {sorted(VALID_PLATFORMS)}"

    def test_version_is_semver_if_present(self, skill_dir):
        fm, _ = parse_frontmatter(skill_dir / "SKILL.md")
        if "version" not in fm:
            return
        version = str(fm["version"])
        assert re.match(r"^\d+\.\d+\.\d+$", version), \
            f"version '{version}' is not semver (expected X.Y.Z)"

    def test_prerequisites_skills_exist(self, skill_dir):
        fm, _ = parse_frontmatter(skill_dir / "SKILL.md")
        prereqs = fm.get("prerequisites") or {}
        if not isinstance(prereqs, dict):
            return
        dep_skills = prereqs.get("skills") or []
        if not dep_skills:
            return
        for dep in dep_skills:
            dep_dir = GLOBAL_SKILLS / dep
            assert dep_dir.is_dir(), \
                f"prerequisites.skills references '{dep}' which has no directory in global-skills/"

    def test_related_skills_is_list_if_present(self, skill_dir):
        fm, _ = parse_frontmatter(skill_dir / "SKILL.md")
        related = fm.get("related_skills")
        if related is None:
            return
        assert isinstance(related, list), "related_skills must be a list"
        # Note: values may reference skills outside global-skills/ (plugins, user skills).
        # Type check only — no existence check.

    def test_prerequisites_commands_is_list_if_present(self, skill_dir):
        fm, _ = parse_frontmatter(skill_dir / "SKILL.md")
        prereqs = fm.get("prerequisites") or {}
        if not isinstance(prereqs, dict):
            return
        cmds = prereqs.get("commands")
        if cmds is None:
            return
        assert isinstance(cmds, list), "prerequisites.commands must be a list"

    def test_tags_is_list_if_present(self, skill_dir):
        fm, _ = parse_frontmatter(skill_dir / "SKILL.md")
        tags = fm.get("tags")
        if tags is None:
            return
        assert isinstance(tags, list), "tags must be a list"
        assert all(isinstance(t, str) for t in tags), "all tags must be strings"

"""Tests for lib/install-update.sh detect_changed_sections()."""
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
LIB = REPO_ROOT / "lib" / "install-update.sh"


def detect(changed: str) -> list[str]:
    """Call detect_changed_sections() via bash subprocess."""
    r = subprocess.run(
        ["bash", "-c", f"source {LIB} && detect_changed_sections \"$CHANGED\""],
        capture_output=True, text=True, check=True,
        env={**os.environ, "CHANGED": changed},
    )
    return [line for line in r.stdout.splitlines() if line]


# ── detect_changed_sections unit tests ──────────────────────────────────────

def test_pyproject_toml_returns_uv_sync():
    assert detect("pyproject.toml") == ["uv_sync"]


def test_uv_lock_returns_uv_sync():
    assert detect("uv.lock") == ["uv_sync"]


def test_global_skills_returns_skills():
    sections = detect("global-skills/my-skill/skill.md")
    assert set(sections) == {"skills", "jdocmunch"}


def test_install_reliability_returns_skills():
    assert detect("install-reliability.sh") == ["skills"]


def test_install_reliability_bak_returns_empty():
    assert detect("install-reliability.sh.bak") == []


def test_mcp_clients_returns_mcp_templates():
    assert detect("mcp-clients/claude-desktop-config-fragment.json.tmpl") == ["mcp_templates"]


def test_md_change_returns_jdocmunch():
    assert detect("README.md") == ["jdocmunch"]


def test_install_sh_returns_full():
    assert detect("install.sh") == ["full"]


def test_multiple_changes_returns_multiple_sections():
    changed = "pyproject.toml\nglobal-skills/foo/skill.md"
    sections = detect(changed)
    assert set(sections) == {"uv_sync", "skills", "jdocmunch"}


def test_unrelated_file_returns_empty():
    assert detect("scripts/auto-maintain.sh") == []


def test_install_sh_alongside_others_includes_full():
    changed = "install.sh\npyproject.toml"
    sections = detect(changed)
    assert set(sections) == {"full", "uv_sync"}

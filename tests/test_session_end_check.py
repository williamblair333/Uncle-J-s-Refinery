"""Tests for scripts/session-end-check.sh."""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "session-end-check.sh"

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
}

BASIC_CONFIG = """\
version: 1
trigger:
  file_types: [".sh", ".py"]
mandatory:
  - CHANGELOG.md
  - HANDOFF.md
"""


def make_repo(tmp_path: Path, config: str | None = None) -> Path:
    """Create a minimal git repo, optionally with a .session-end.yml."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, env=GIT_ENV)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True)
    # Initial commit so HEAD exists
    (tmp_path / "init.txt").write_text("init")
    subprocess.run(["git", "add", "init.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True, env=GIT_ENV)
    if config is not None:
        (tmp_path / ".session-end.yml").write_text(config)
        subprocess.run(["git", "add", ".session-end.yml"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add config"], cwd=tmp_path, check=True, capture_output=True, env=GIT_ENV)
    return tmp_path


def stage(repo: Path, name: str, content: str = "content") -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    subprocess.run(["git", "add", name], cwd=repo, check=True, capture_output=True)


def run_hook(repo: Path, mode: str | None = None) -> subprocess.CompletedProcess:
    cmd = ["bash", str(SCRIPT)]
    if mode:
        cmd.append(mode)
    return subprocess.run(cmd, cwd=repo, capture_output=True, text=True)


# ── pre-commit mode ───────────────────────────────────────────────────────────

def test_no_config_passes(tmp_path):
    repo = make_repo(tmp_path)
    stage(repo, "script.sh")
    assert run_hook(repo).returncode == 0


def test_no_trigger_files_passes(tmp_path):
    """Pure doc commit — file-type gate lets it through."""
    repo = make_repo(tmp_path, BASIC_CONFIG)
    stage(repo, "README.md", "updated")
    assert run_hook(repo).returncode == 0


def test_triggered_all_mandatory_staged_passes(tmp_path):
    repo = make_repo(tmp_path, BASIC_CONFIG)
    stage(repo, "script.sh")
    stage(repo, "CHANGELOG.md", "## entry")
    stage(repo, "HANDOFF.md", "## handoff")
    assert run_hook(repo).returncode == 0


def test_triggered_missing_changelog_blocks(tmp_path):
    repo = make_repo(tmp_path, BASIC_CONFIG)
    stage(repo, "script.sh")
    stage(repo, "HANDOFF.md", "## handoff")
    result = run_hook(repo)
    assert result.returncode == 1
    assert "CHANGELOG.md" in result.stdout


def test_triggered_missing_handoff_blocks(tmp_path):
    repo = make_repo(tmp_path, BASIC_CONFIG)
    stage(repo, "script.sh")
    stage(repo, "CHANGELOG.md", "## entry")
    result = run_hook(repo)
    assert result.returncode == 1
    assert "HANDOFF.md" in result.stdout


def test_triggered_missing_both_lists_all(tmp_path):
    repo = make_repo(tmp_path, BASIC_CONFIG)
    stage(repo, "script.sh")
    result = run_hook(repo)
    assert result.returncode == 1
    assert "CHANGELOG.md" in result.stdout
    assert "HANDOFF.md" in result.stdout


def test_error_message_contains_hint(tmp_path):
    repo = make_repo(tmp_path, BASIC_CONFIG)
    stage(repo, "script.sh")
    result = run_hook(repo)
    assert "--no-verify" in result.stdout


# ── stop-hook mode ────────────────────────────────────────────────────────────

def test_stop_hook_never_blocks_even_when_missing(tmp_path):
    """Stop hook mode must always exit 0."""
    repo = make_repo(tmp_path, BASIC_CONFIG)
    # Modify a code file without updating mandatory docs
    (repo / "script.sh").write_text("changed")
    subprocess.run(["git", "add", "script.sh"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "oops"], cwd=repo, check=True, capture_output=True, env=GIT_ENV)
    # Now in stop-hook mode: code changed, docs not — should still exit 0
    assert run_hook(repo, "--stop-hook").returncode == 0


def test_stop_hook_passes_when_no_config(tmp_path):
    repo = make_repo(tmp_path)
    assert run_hook(repo, "--stop-hook").returncode == 0


def test_stop_hook_passes_when_not_triggered(tmp_path):
    repo = make_repo(tmp_path, BASIC_CONFIG)
    (repo / "README.md").write_text("updated")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "doc"], cwd=repo, check=True, capture_output=True, env=GIT_ENV)
    assert run_hook(repo, "--stop-hook").returncode == 0

"""The repo CLAUDE.md is the routing policy's source, and install.sh / refinery-doctor
deploy it to ~/.claude/CLAUDE.md. Sessions in this repo used to load both copies
(~5k tokens twice). `.claude/settings.json` now excludes the repo copy from auto-load.

These checks pin the exclusion to exactly the repo's own copies: never the global
file (that would leave sessions with no policy) and never another project's.
"""

import fnmatch
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text())
PATTERNS = SETTINGS.get("claudeMdExcludes", [])


def excluded(path: str) -> bool:
    # Claude Code globs absolute paths; fnmatch's * also crosses "/", so ** behaves.
    return any(fnmatch.fnmatch(path, p) for p in PATTERNS)


def test_repo_copy_and_worktree_copies_are_excluded():
    assert excluded("/opt/proj/Uncle-J-s-Refinery/CLAUDE.md")
    assert excluded("/c/opt/proj/Uncle-J-s-Refinery/CLAUDE.md")
    assert excluded("/opt/proj/Uncle-J-s-Refinery/.claude/worktrees/agent-1/CLAUDE.md")


def test_global_and_other_projects_are_never_excluded():
    assert not excluded("/home/bill/.claude/CLAUDE.md")
    assert not excluded("/opt/proj/other/CLAUDE.md")
    assert not excluded("/opt/proj/jaredrhod/CLAUDE.md")
    assert not excluded("/opt/proj/Uncle-J-s-Refinery/docs/CLAUDE.md")


def test_repo_copy_still_exists_as_the_deploy_source():
    # install.sh §6b and refinery-doctor claude-md-sync read it; excluding it from
    # auto-load must not mean deleting or stubbing it.
    text = (REPO_ROOT / "CLAUDE.md").read_text()
    assert text.startswith("# Retrieval Stack Routing Policy")
    assert len(text) > 10_000

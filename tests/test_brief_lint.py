"""scripts/delegate/brief_lint.py: agy briefs that ask for what agy may not do are refused up front."""
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "delegate"))
import brief_lint as bl  # noqa: E402

BRIEFS = json.loads((REPO / "tests" / "fixtures" / "agy_briefs_2026-11-01.json").read_text())
RULES = (["python", "python3", "pytest", "git status", "git log", "just", "grep"],
         ["rm", "git checkout", "git push", "curl"],
         ["/opt/proj/", "/tmp/claude-1000/"])


def kinds(problems):
    out = set()
    for p in problems:
        if "bare commands" in p:
            out.add("venv")
        elif "branch" in p:
            out.add("branch")
        elif "readable roots" in p:
            out.add("path")
        elif "denied" in p:
            out.add("denied")
        elif "no allow rule" in p:
            out.add("unlisted")
    return out


# This session's real briefs (2026-11-01): what each one broke.
@pytest.mark.parametrize("i,expected", [
    (0, {"venv"}),                      # ran .venv/bin/python (allowed by luck that run)
    (1, {"venv", "branch", "path"}),    # git checkout -b denied; ~/.code-index unreadable
    (2, {"venv", "branch", "path"}),    # same, second try
    (3, {"venv"}),                      # .venv/bin/python denied: "user denied permission"
])
def test_real_briefs_from_11_01(i, expected, monkeypatch):
    # lint() skips paths that don't exist, and these briefs name a file only Bill's machine has,
    # so without this the test can't pass on CI (red on main from at least 2026-11-04).
    real_exists = os.path.exists
    monkeypatch.setattr(bl.os.path, "exists",
                        lambda p: str(p).startswith("/home/bill/.code-index/") or real_exists(p))
    b = BRIEFS[i]
    assert kinds(bl.lint(b["prompt"], b["cwd"], RULES)) >= expected


def test_the_corrected_brief_passes():
    b = BRIEFS[3]
    fixed = b["prompt"].replace(".venv/bin/python -m pytest", "python3 -m pytest")
    assert bl.lint(fixed, b["cwd"], RULES) == []


def test_denied_and_unlisted_commands(tmp_path):
    p = bl.lint("Run: git push origin main\nThen run `docker ps`.", str(tmp_path), RULES)
    assert kinds(p) == {"denied", "unlisted"}


def test_env_prefix_and_chains(tmp_path):
    assert bl.lint("Run: FOO=1 pytest -q && git status", str(tmp_path), RULES) == []
    assert kinds(bl.lint("Run: pytest -q; rm -rf x", str(tmp_path), RULES)) == {"denied"}


def test_negated_instructions_are_not_requests(tmp_path):
    text = ("Do not run git. Do not create a branch. Never read /etc/hostname.\n"
            "Do not run: git checkout -b x")
    assert bl.lint(text, str(tmp_path), RULES) == []


def test_descriptive_paths_that_do_not_exist_pass(tmp_path):
    assert bl.lint("the log line says /tmp/pytest-of-x/nowhere and ~/nope/never", str(tmp_path), RULES) == []


def test_existing_path_outside_roots_is_flagged_inside_is_not(tmp_path):
    outside = "/etc/hostname"
    inside = tmp_path / "f.txt"
    inside.write_text("x")
    p = bl.lint(f"Read {outside} and {inside}", str(tmp_path), RULES)
    assert kinds(p) == {"path"} and outside in p[0]


def test_bare_top_level_dirs_are_description(tmp_path):
    # brief 3 (11-01): "Build a FAKE /proc and socket dir under tmp_path"
    assert bl.lint("Build a FAKE /proc and a fake /run under tmp_path", str(tmp_path), RULES) == []


def test_urls_are_not_paths(tmp_path):
    assert bl.lint("See https://example.com/docs/x and http://10.0.0.100:3000/bill", str(tmp_path), RULES) == []


def test_branch_phrasings(tmp_path):
    for t in ("Work on a new git branch `feat/x`.", "Create a branch for it.", "git checkout -b feat/x"):
        assert kinds(bl.lint(t, str(tmp_path), RULES)) == {"branch"}, t


def test_real_permissions_file_parses():
    rules = bl.load_rules()
    assert rules is not None
    allow, deny, roots = rules
    assert "python3" in allow and "git checkout" in deny and "/opt/proj/" in roots


def test_missing_permissions_skips_command_rule_only(tmp_path):
    assert bl.load_rules(tmp_path / "missing.json") is None


def test_run_agy_refuses_before_calling_agy(monkeypatch, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("delegate_server_lint", REPO / "scripts/delegate/server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)  # several test files import a module named "server"
    monkeypatch.setattr(server, "LOG_PATH", None)
    called = []
    out = server.run_agy("Create a new branch and run: .venv/bin/python -m pytest", cwd=str(tmp_path),
                         ask=lambda *a, **k: called.append(1) or {"ok": True})
    assert out["error"] == "brief_lint" and not called and out["problems"]

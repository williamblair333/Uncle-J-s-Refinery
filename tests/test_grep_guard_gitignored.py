"""grep-guard allows shell reads of gitignored files: jcodemunch never indexes them, so no
structured route exists (2026-11-19: `wc -l`/`sed`/`grep` on gitignored
review/…/qwen_scenes.py was blocked twice). Tracked files and symlinks that land on
tracked source stay denied."""
import json
import os
import shutil
import subprocess

import tempfile

import pytest

HOOK = os.path.join(os.path.dirname(__file__), "..", "hooks", "discipline", "grep-guard.sh")
# Denials log to a throwaway root, never the live state/hook-blocks.log.
ENV = {**os.environ, "UNCLE_J_PROJ_ROOT": tempfile.mkdtemp(prefix="grep-guard-ign-test-")}


def _decide(cmd, cwd, env=None):
    payload = {"tool_input": {"command": cmd}, "session_id": "test", "cwd": str(cwd)}
    r = subprocess.run(["bash", HOOK], input=json.dumps(payload), capture_output=True,
                       text=True, env={**(env or ENV), "GREP_GUARD_DEBUG": "1"})
    return '"deny"' in r.stdout.replace(" ", ""), r.stderr


@pytest.fixture
def ign_repo(tmp_path):
    r = tmp_path / "repo"
    (r / "scripts").mkdir(parents=True)
    (r / "review" / "sub").mkdir(parents=True)
    (r / "scripts" / "tool.py").write_text("x\n")
    (r / "review" / "sub" / "scenes.py").write_text("x\n")
    (r / "review" / "forced.py").write_text("x\n")
    (r / "review" / "link.py").symlink_to(r / "scripts" / "tool.py")
    (r / "review" / "dirlink").symlink_to(r / "scripts")
    (r / ".gitignore").write_text("review/\n")
    git = ["git", "-C", str(r), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    subprocess.run(git + ["add", ".gitignore", "scripts/tool.py"], check=True)
    subprocess.run(git + ["add", "-f", "review/forced.py"], check=True)   # tracked despite ignore
    subprocess.run(git + ["commit", "-qm", "init"], check=True)
    return r


ALLOW = [
    "wc -l review/sub/scenes.py",
    "sed -n 1,60p review/sub/scenes.py",
    "grep -n -E 'comfy|ram' review/sub/scenes.py",
    "cat review/sub/scenes.py",
    "head -5 ./review/sub/scenes.py",
    "{repo}/review/sub/scenes.py:cat",          # absolute spelling (see _cmd)
]
DENY = [
    "cat scripts/tool.py",                     # tracked source: unchanged
    "cat review/link.py",                      # ignored path, lands on tracked source
    "cat review/dirlink/tool.py",              # through a symlinked dir into tracked source
    "cat review/forced.py",                    # ignored pattern but tracked (git add -f)
    "cat review/../scripts/tool.py",           # .. hop out of the ignored dir
    "cat review/sub/scenes.py scripts/tool.py",  # one ignored + one tracked operand
    "grep -rn foo review/ scripts/",           # recursive: a tracked tree is still named
]


def _cmd(c, repo):
    if c.endswith(":cat"):
        return "cat " + c[:-4].format(repo=repo)
    return c


@pytest.mark.parametrize("cmd", ALLOW)
def test_gitignored_reads_allowed(ign_repo, cmd):
    denied, err = _decide(_cmd(cmd, ign_repo), ign_repo)
    assert denied is False, err
    assert "path=legacy" not in err, err   # `wc` alone exits at the prefilter (no path line)


@pytest.mark.parametrize("cmd", DENY)
def test_tracked_or_escaping_reads_still_denied(ign_repo, cmd):
    denied, err = _decide(cmd, ign_repo)
    assert denied is True, err


def _legacy_env(tmp_path):
    shim = tmp_path / "bin"
    shim.mkdir()
    for tool in ("jq", "grep", "sed", "realpath", "git", "date", "tr", "head", "iconv",
                 "wc", "find", "mkdir", "rmdir", "mv", "cat", "bash", "dirname"):
        p = shutil.which(tool)
        if p:
            os.symlink(p, shim / tool)
    return {**ENV, "PATH": str(shim)}


def test_legacy_path_allows_gitignored_and_denies_tracked(ign_repo, tmp_path):
    env = _legacy_env(tmp_path)
    denied, err = _decide("cat review/sub/scenes.py", ign_repo, env)
    assert denied is False and "path=legacy" in err, err
    for cmd in ("cat scripts/tool.py", "cat review/link.py", "cat review/forced.py"):
        denied, err = _decide(cmd, ign_repo, env)
        assert denied is True, (cmd, err)

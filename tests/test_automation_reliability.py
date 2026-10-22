"""
Behaviour tests for the automation-reliability fixes (2026-10-22):

1. scripts/check-local-main-unpushed.sh — local main ahead of the remote is
   detected via `git ls-remote`, not the stale origin/main tracking ref.
2. scripts/post-merge-hook.sh — a merge touching only code (no human ACTIONS)
   still re-indexes jcodemunch.
3. scripts/healthcheck-notify.sh — a stale jcodemunch index is re-indexed and
   re-checked once before anything is reported.
4. scripts/commit_doc_guard.py — the doc gate fires on real `git commit` in this
   repo only: not on read-only git calls, not in nested independent clones.

Every git case drives real repositories; nothing fakes git.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import commit_doc_guard as cdg  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def _init(path, origin=None):
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    _git(path, "config", "commit.gpgsign", "false")
    if origin:
        _git(path, "remote", "add", "origin", str(origin))


def _commit(path, name, text="x"):
    p = Path(path) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", f"add {name}")
    return _git(path, "rev-parse", "HEAD")


# ── 1. unpushed local main ──────────────────────────────────────────────────

UNPUSHED = SCRIPTS / "check-local-main-unpushed.sh"


@pytest.fixture()
def pushed_repo(tmp_path):
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    work = tmp_path / "work"
    _init(work, origin=bare)
    _commit(work, "a.txt")
    _git(work, "push", "-q", "origin", "main")
    return work


def _unpushed(work):
    r = subprocess.run(["bash", str(UNPUSHED), str(work)], capture_output=True, text=True)
    assert r.stderr == "", r.stderr
    return r.returncode, r.stdout.strip()


def test_unpushed_in_sync_is_ok(pushed_repo):
    rc, out = _unpushed(pushed_repo)
    assert rc == 0 and out.startswith("OK"), out


def test_unpushed_detects_local_commits_ahead(pushed_repo):
    _commit(pushed_repo, "b.txt")
    _commit(pushed_repo, "c.txt")
    rc, out = _unpushed(pushed_repo)
    assert rc == 1 and out.startswith("AHEAD 2 "), out
    assert "2 commit(s)" in out


def test_unpushed_sees_ahead_even_when_tracking_ref_is_stale(pushed_repo, tmp_path):
    """The bug: `git log HEAD..origin/main` reads the tracking ref. Delete it —
    ls-remote must still find the remote tip and count the unpushed commit."""
    _commit(pushed_repo, "b.txt")
    _git(pushed_repo, "update-ref", "-d", "refs/remotes/origin/main")
    rc, out = _unpushed(pushed_repo)
    assert rc == 1 and out.startswith("AHEAD 1 "), out


def test_unpushed_checks_main_not_current_branch(pushed_repo):
    _git(pushed_repo, "checkout", "-q", "-b", "feat")
    _commit(pushed_repo, "feat.txt")  # unpushed, but not on main
    rc, out = _unpushed(pushed_repo)
    assert rc == 0, out


def test_unpushed_behind_is_not_a_warning(pushed_repo, tmp_path):
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)], check=True)
    _git(other, "config", "user.email", "t@t")
    _git(other, "config", "user.name", "t")
    _commit(other, "remote-only.txt")
    _git(other, "push", "-q", "origin", "main")
    rc, out = _unpushed(pushed_repo)
    assert rc == 0 and out.startswith("OK"), out


def test_unpushed_offline_skips(pushed_repo, tmp_path):
    _git(pushed_repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    rc, out = _unpushed(pushed_repo)
    assert rc == 0 and out.startswith("SKIP"), out


def test_unpushed_no_origin_skips(tmp_path):
    _init(tmp_path / "solo")
    _commit(tmp_path / "solo", "a.txt")
    rc, out = _unpushed(tmp_path / "solo")
    assert rc == 0 and out.startswith("SKIP"), out


def test_session_start_and_healthcheck_wire_the_check():
    assert "check-local-main-unpushed.sh" in (SCRIPTS / "session-start-autofix.sh").read_text(encoding="utf-8")
    hc = (ROOT / "healthcheck.sh").read_text(encoding="utf-8")
    assert "check_local_main_unpushed()" in hc
    assert "\ncheck_local_main_unpushed\n" in hc


# ── 2. post-merge re-indexes on code-only merges ────────────────────────────

def _merge_repo(tmp_path, changed_file):
    repo = tmp_path / "repo"
    _init(repo)
    _commit(repo, "README.md", "base")
    before = _git(repo, "rev-parse", "HEAD")
    _commit(repo, changed_file, "changed")
    _git(repo, "update-ref", "ORIG_HEAD", before)
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    shutil.copy(SCRIPTS / "post-merge-hook.sh", hooks / "post-merge")
    marker = tmp_path / "reindexed"
    stub = repo / "scripts" / "jcodemunch-reindex.sh"
    stub.parent.mkdir(exist_ok=True)
    stub.write_text(f"#!/usr/bin/env bash\ntouch '{marker}'\n")
    return repo, marker


@pytest.mark.parametrize("changed", [
    "scripts/auto-maintain.sh",
    "scripts/healthcheck-notify.sh",
    "hooks/discipline/foo.sh",
    "scripts/lib/thing.py",
    "scripts/no-extension-tool",
])
def test_post_merge_reindexes_code_only_merge(tmp_path, changed):
    repo, marker = _merge_repo(tmp_path, changed)
    env = {k: v for k, v in os.environ.items() if not k.startswith("TELEGRAM_")}
    r = subprocess.run(["bash", str(repo / ".git" / "hooks" / "post-merge")], cwd=repo,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert marker.exists(), (repo / "state" / "post-merge.log").read_text()


def test_post_merge_docs_only_does_not_reindex_code(tmp_path):
    repo, marker = _merge_repo(tmp_path, "docs/notes.md")
    env = {k: v for k, v in os.environ.items() if not k.startswith("TELEGRAM_")}
    subprocess.run(["bash", str(repo / ".git" / "hooks" / "post-merge")], cwd=repo,
                   capture_output=True, text=True, env=env, check=True)
    assert not marker.exists()


# ── 3. 07:00 healthcheck-notify heals a stale index before reporting ────────

def _notify_tree(tmp_path, reindex_ok=True):
    root = tmp_path / "proj"
    (root / "scripts").mkdir(parents=True)
    (root / "lib").mkdir()
    shutil.copy(SCRIPTS / "healthcheck-notify.sh", root / "scripts" / "healthcheck-notify.sh")
    (root / ".env").write_text("TELEGRAM_BOT_TOKEN=t\nTELEGRAM_CHAT_ID=c\n")
    sent = tmp_path / "sent.txt"
    (root / "lib" / "notify.sh").write_text(
        f"notify_send_text() {{ printf '%s\\n' \"$1\" >> '{sent}'; }}\n")
    stamp = tmp_path / "indexed"
    (root / "healthcheck.sh").write_text(
        "#!/usr/bin/env bash\n"
        f"if [ -f '{stamp}' ]; then echo 'HEALTHCHECK: ok'; exit 0; fi\n"
        "printf '    X   jcodemunch index is 2 commit(s) stale (indexed=a current=b)\\n' >&2\n"
        "echo 'HEALTHCHECK: fail (1) -- jcodemunch-index-stale'; exit 1\n")
    (root / "scripts" / "jcodemunch-reindex.sh").write_text(
        f"#!/usr/bin/env bash\ntouch '{stamp}'\n" if reindex_ok else "#!/usr/bin/env bash\nexit 1\n")
    return root, sent


def test_notify_reindexes_stale_index_and_stays_quiet(tmp_path):
    root, sent = _notify_tree(tmp_path)
    subprocess.run(["bash", str(root / "scripts" / "healthcheck-notify.sh")], check=True)
    assert not sent.exists(), sent.read_text()
    log = (root / "state" / "healthcheck-notify.log").read_text()
    assert "reindexing before reporting" in log and "re-running healthcheck" in log


def test_notify_reports_when_reindex_fails(tmp_path):
    root, sent = _notify_tree(tmp_path, reindex_ok=False)
    subprocess.run(["bash", str(root / "scripts" / "healthcheck-notify.sh")], check=True)
    assert "jcodemunch index is 2 commit(s) stale" in sent.read_text()


# ── 4. commit doc gate: real commits in this repo only ──────────────────────

@pytest.mark.parametrize("cmd", [
    "git rev-parse HEAD^{commit}",
    "git ls-remote origin refs/heads/main  # before commit",
    "gh api repos/x/y/commits/abc && git log -1",
    "git log --format=%H -1 commit",
    "echo 'git commit -m x'",
    "git show HEAD:commit.txt",
    "cat <<'EOF'\ngit commit -m inside-heredoc\nEOF",
])
def test_parser_ignores_non_commits(cmd):
    assert not [c for c in cdg.parse_git_calls(cmd, "/tmp") if c.subcommand == "commit"]


@pytest.mark.parametrize("cmd,expected_dir", [
    ("git commit -m msg", "/w"),
    ("git -C /other commit -m msg", "/other"),
    ("git -C sub -c core.x=1 commit -q", "/w/sub"),
    ("cd review/rea && git commit -m x", "/w/review/rea"),
    ("git add -A; FOO=1 git --no-pager commit", "/w"),
    ('git commit -m "$(cat <<\'EOF\'\nfix: thing\n\ngit push later\nEOF\n)"', "/w"),
])
def test_parser_finds_commits_and_their_dir(cmd, expected_dir):
    commits = [c for c in cdg.parse_git_calls(cmd, "/w") if c.subcommand == "commit"]
    assert len(commits) == 1 and commits[0].cwd == expected_dir


@pytest.mark.parametrize("args,all_flag,msgs", [
    (["-m", "chk: 12:00"], False, ["chk: 12:00"]),
    (["-am", "x"], True, ["x"]),
    (["-mchk:x"], False, ["chk:x"]),
    (["--message=y", "-a"], True, ["y"]),
    (["-F", "-a"], False, []),  # -a is the value of -F here
])
def test_commit_flags(args, all_flag, msgs):
    assert cdg.commit_flags(args) == (all_flag, msgs)


@pytest.fixture()
def gated(tmp_path):
    """Repo with .session-end.yml, a staged .py change, a nested independent clone
    (gitignored, like review/rea) and a linked worktree."""
    repo = tmp_path / "repo"
    _init(repo)
    (repo / ".session-end.yml").write_text(
        "trigger:\n  file_types: ['.py', '.sh']\nmandatory:\n  - CHANGELOG.md\n  - HANDOFF.md\n")
    (repo / ".gitignore").write_text("review/\n")
    _commit(repo, "CHANGELOG.md")
    (repo / "code.py").write_text("x = 1\n")
    _git(repo, "add", "code.py")
    nested = repo / "review" / "rea"
    _init(nested)
    _commit(nested, "a.txt")
    (nested / "tool.py").write_text("y = 2\n")
    _git(nested, "add", "tool.py")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "wt", str(wt))
    (wt / "other.py").write_text("z = 3\n")
    _git(wt, "add", "other.py")
    return repo, nested, wt


def _guard(command, cwd, root):
    payload = json.dumps({"tool_input": {"command": command}, "cwd": str(cwd)})
    r = subprocess.run(["bash", str(SCRIPTS / "commit-doc-guard.sh")], input=payload,
                       capture_output=True, text=True,
                       env={**os.environ, "COMMIT_DOC_GUARD_ROOT": str(root)})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def test_gate_blocks_real_commit_missing_docs(gated):
    repo, _, _ = gated
    out = _guard("git commit -m 'feat: x'", repo, repo)
    reason = _denied(out)
    assert "CHANGELOG.md" in reason and "HANDOFF.md" in reason


def _denied(out):
    # A per-call deny, never {"continue": false}: that ends the whole turn (subagents stopped mid-task).
    assert out and "continue" not in out
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse" and hso["permissionDecision"] == "deny"
    return hso["permissionDecisionReason"]


@pytest.mark.parametrize("cmd", [
    "git commit --no-verify -m 'feat: x'",
    "git commit -n -m 'feat: x'",
    "git commit -nm 'feat: x'",
    "git commit -am x --no-verify",
])
def test_gate_blocks_no_verify(gated, cmd):
    repo, _, _ = gated
    assert "--no-verify" in _denied(_guard(cmd, repo, repo))


@pytest.mark.parametrize("cmd", [
    "git commit -m 'chk: wip' --no-verify",
    "git commit -m 'note: -n is a flag'",
])
def test_gate_no_verify_exemptions(gated, cmd):
    repo, _, _ = gated
    for f in ("CHANGELOG.md", "HANDOFF.md"):
        (repo / f).write_text("updated\n")
        _git(repo, "add", f)
    assert _guard(cmd, repo, repo) is None


def test_gate_passes_when_docs_staged(gated):
    repo, _, _ = gated
    for f in ("CHANGELOG.md", "HANDOFF.md"):
        (repo / f).write_text("updated\n")
        _git(repo, "add", f)
    assert _guard("git commit -m 'feat: x'", repo, repo) is None


@pytest.mark.parametrize("cmd", [
    "git rev-parse HEAD",
    "git ls-remote origin refs/heads/main",
    "gh api repos/o/r/commits",
    "git log --oneline -3 && echo commit",
])
def test_gate_ignores_read_only_calls(gated, cmd):
    repo, _, _ = gated
    assert _guard(cmd, repo, repo) is None


def test_gate_ignores_nested_independent_clone(gated):
    repo, nested, _ = gated
    assert _guard("git commit -m x", nested, repo) is None
    assert _guard("cd review/rea && git commit -m x", repo, repo) is None
    assert _guard(f"git -C {nested} commit -m x", repo, repo) is None


def test_gate_applies_to_linked_worktree(gated):
    repo, _, wt = gated
    _denied(_guard("git commit -m x", wt, repo))


def test_gate_exempts_checkpoint_and_defers_when_staging_inline(gated):
    repo, _, _ = gated
    assert _guard("git commit -q -m 'chk: 10:00:00'", repo, repo) is None
    assert _guard("git add CHANGELOG.md HANDOFF.md && git commit -m x", repo, repo) is None
    assert _guard("git commit -am x", repo, repo) is None


def test_gate_doc_only_commit_passes(gated):
    repo, _, _ = gated
    _git(repo, "reset", "-q", "code.py")
    (repo / "notes.md").write_text("n\n")
    _git(repo, "add", "notes.md")
    assert _guard("git commit -m docs", repo, repo) is None


def test_gate_fails_open_on_garbage_payload(tmp_path):
    r = subprocess.run(["bash", str(SCRIPTS / "commit-doc-guard.sh")], input="not json",
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == ""


def test_settings_wires_shared_guard():
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cmds = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert any("commit-doc-guard.sh" in c for c in cmds)
    assert not any("\\bcommit\\b" in c for c in cmds)

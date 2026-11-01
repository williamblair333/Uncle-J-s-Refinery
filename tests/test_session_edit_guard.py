"""Tests for scripts/session_edit_guard.py."""
import io
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import session_edit_guard as g


def make_proc_entry(
    proc: Path,
    pid: int,
    parent_pid: int = 1,
    cmdline: bytes = b"claude\0--flag\0",
    cwd: Path | None = None,
) -> Path:
    pdir = proc / str(pid)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "status").write_text(f"PPid:\t{parent_pid}\n")
    (pdir / "cmdline").write_bytes(cmdline)
    if cwd is not None:
        link = pdir / "cwd"
        if link.is_symlink() or link.exists():
            link.unlink()
        os.symlink(str(cwd), str(link))
    return pdir


def make_socket(sock_dir: Path, pid: int) -> Path:
    sock_dir.mkdir(parents=True, exist_ok=True)
    sock_path = sock_dir / f"{pid}.sock"
    sock_path.touch()
    return sock_path


def make_checkout(path: Path, is_worktree: bool = False) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git_target = path / ".git"
    if is_worktree:
        git_target.write_text("gitdir: /fake/path/.git/worktrees/wt\n")
    else:
        git_target.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(autouse=True)
def patch_log(monkeypatch, tmp_path):
    log_file = tmp_path / "fake-hook-blocks.log"
    monkeypatch.setattr(g, "LOG", log_file)


@pytest.fixture
def env(tmp_path):
    proc = tmp_path / "proc"
    proc.mkdir()
    sock_dir = tmp_path / "socks"
    sock_dir.mkdir()

    own_checkout = make_checkout(tmp_path / "own_repo")

    # Ancestor chain: me (100) -> claude_pid (10) -> init (1)
    claude_pid = 10
    me = 100
    make_proc_entry(proc, claude_pid, parent_pid=1, cmdline=b"claude\0--flag\0", cwd=own_checkout)
    make_socket(sock_dir, claude_pid)
    make_proc_entry(proc, me, parent_pid=claude_pid, cmdline=b"python3\0", cwd=own_checkout)

    return {
        "proc": proc,
        "sock_dir": sock_dir,
        "me": me,
        "claude_pid": claude_pid,
        "own_checkout": own_checkout,
        "tmp_path": tmp_path,
    }


def test_deny_edit_into_other_checkout_with_live_session(env):
    proc = env["proc"]
    sock_dir = env["sock_dir"]
    me = env["me"]
    own_checkout = env["own_checkout"]
    tmp_path = env["tmp_path"]

    other_checkout = make_checkout(tmp_path / "other_repo")
    target_file = other_checkout / "file.py"
    target_file.touch()

    other_pid = 20
    make_proc_entry(proc, other_pid, parent_pid=1, cmdline=b"claude\0--flag\0", cwd=other_checkout)
    make_socket(sock_dir, other_pid)

    data = {"cwd": str(own_checkout), "tool_input": {"file_path": str(target_file)}}
    reason = g.decide(data, sock_dir, proc, me)
    assert reason is not None
    assert str(other_checkout.resolve()) in reason
    assert str(other_pid) in reason


def test_allow_edit_into_own_checkout_with_concurrent_session(env):
    proc = env["proc"]
    sock_dir = env["sock_dir"]
    me = env["me"]
    own_checkout = env["own_checkout"]

    target_file = own_checkout / "file.py"
    target_file.touch()

    other_pid = 20
    make_proc_entry(proc, other_pid, parent_pid=1, cmdline=b"claude\0--flag\0", cwd=own_checkout)
    make_socket(sock_dir, other_pid)

    data = {"cwd": str(own_checkout), "tool_input": {"file_path": str(target_file)}}
    reason = g.decide(data, sock_dir, proc, me)
    assert reason is None


def test_allow_edit_into_other_checkout_without_live_session(env):
    proc = env["proc"]
    sock_dir = env["sock_dir"]
    me = env["me"]
    own_checkout = env["own_checkout"]
    tmp_path = env["tmp_path"]

    other_checkout = make_checkout(tmp_path / "other_repo")
    target_file = other_checkout / "file.py"
    target_file.touch()

    data = {"cwd": str(own_checkout), "tool_input": {"file_path": str(target_file)}}
    reason = g.decide(data, sock_dir, proc, me)
    assert reason is None


def test_ancestor_claude_pid_never_counted_as_another_session(env):
    proc = env["proc"]
    sock_dir = env["sock_dir"]
    claude_pid = env["claude_pid"]
    me = env["me"]
    own_checkout = env["own_checkout"]
    tmp_path = env["tmp_path"]

    other_checkout = make_checkout(tmp_path / "other_repo")
    target_file = other_checkout / "file.py"
    target_file.touch()

    # Move the ancestor claude session's cwd to target checkout
    link = proc / str(claude_pid) / "cwd"
    link.unlink()
    os.symlink(str(other_checkout), str(link))

    data = {"cwd": str(own_checkout), "tool_input": {"file_path": str(target_file)}}
    reason = g.decide(data, sock_dir, proc, me)
    assert reason is None


def test_socket_with_non_claude_argv0_ignored(env):
    proc = env["proc"]
    sock_dir = env["sock_dir"]
    me = env["me"]
    own_checkout = env["own_checkout"]
    tmp_path = env["tmp_path"]

    other_checkout = make_checkout(tmp_path / "other_repo")
    target_file = other_checkout / "file.py"
    target_file.touch()

    other_pid = 20
    make_proc_entry(proc, other_pid, parent_pid=1, cmdline=b"python3\0--script\0", cwd=other_checkout)
    make_socket(sock_dir, other_pid)

    data = {"cwd": str(own_checkout), "tool_input": {"file_path": str(target_file)}}
    reason = g.decide(data, sock_dir, proc, me)
    assert reason is None


def test_socket_with_missing_proc_entry_ignored(env):
    proc = env["proc"]
    sock_dir = env["sock_dir"]
    me = env["me"]
    own_checkout = env["own_checkout"]
    tmp_path = env["tmp_path"]

    other_checkout = make_checkout(tmp_path / "other_repo")
    target_file = other_checkout / "file.py"
    target_file.touch()

    dead_pid = 20
    make_socket(sock_dir, dead_pid)

    data = {"cwd": str(own_checkout), "tool_input": {"file_path": str(target_file)}}
    reason = g.decide(data, sock_dir, proc, me)
    assert reason is None


def test_nested_worktree_is_own_checkout(env):
    proc = env["proc"]
    sock_dir = env["sock_dir"]
    me = env["me"]
    tmp_path = env["tmp_path"]

    third_checkout = make_checkout(tmp_path / "third_repo")
    outer_checkout = make_checkout(tmp_path / "outer_repo")
    wt_checkout = make_checkout(outer_checkout / "nested_wt", is_worktree=True)

    file_in_wt = wt_checkout / "wt_file.py"
    file_in_wt.touch()
    file_in_outer = outer_checkout / "outer_file.py"
    file_in_outer.touch()

    # Session in outer repo, edit inside worktree -> allowed
    pid_outer = 20
    make_proc_entry(proc, pid_outer, parent_pid=1, cmdline=b"claude\0", cwd=outer_checkout)
    make_socket(sock_dir, pid_outer)

    data_wt = {"cwd": str(third_checkout), "tool_input": {"file_path": str(file_in_wt)}}
    reason = g.decide(data_wt, sock_dir, proc, me)
    assert reason is None

    # Session in worktree, edit in outer repo from third checkout -> only outer session matters
    pid_wt = 30
    make_proc_entry(proc, pid_wt, parent_pid=1, cmdline=b"claude\0", cwd=wt_checkout)
    make_socket(sock_dir, pid_wt)

    data_outer = {"cwd": str(third_checkout), "tool_input": {"file_path": str(file_in_outer)}}
    reason_outer = g.decide(data_outer, sock_dir, proc, me)
    assert reason_outer is not None
    assert str(pid_outer) in reason_outer
    assert str(pid_wt) not in reason_outer

    (sock_dir / f"{pid_outer}.sock").unlink()
    reason_outer_alone = g.decide(data_outer, sock_dir, proc, me)
    assert reason_outer_alone is None


def test_allow_cross_session_edits_marker(env):
    proc = env["proc"]
    sock_dir = env["sock_dir"]
    me = env["me"]
    own_checkout = env["own_checkout"]
    tmp_path = env["tmp_path"]

    other_checkout = make_checkout(tmp_path / "other_repo")
    target_file = other_checkout / "file.py"
    target_file.touch()

    other_pid = 20
    make_proc_entry(proc, other_pid, parent_pid=1, cmdline=b"claude\0", cwd=other_checkout)
    make_socket(sock_dir, other_pid)

    marker = other_checkout / ".claude" / "allow-cross-session-edits"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()

    data = {"cwd": str(own_checkout), "tool_input": {"file_path": str(target_file)}}
    reason = g.decide(data, sock_dir, proc, me)
    assert reason is None


def test_relative_file_path_resolved_against_data_cwd(env):
    proc = env["proc"]
    sock_dir = env["sock_dir"]
    me = env["me"]
    own_checkout = env["own_checkout"]
    tmp_path = env["tmp_path"]

    other_checkout = make_checkout(tmp_path / "other_repo")
    target_file = other_checkout / "sub" / "file.py"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.touch()

    other_pid = 20
    make_proc_entry(proc, other_pid, parent_pid=1, cmdline=b"claude\0", cwd=other_checkout)
    make_socket(sock_dir, other_pid)

    rel_path = os.path.relpath(target_file, own_checkout)
    data = {"cwd": str(own_checkout), "tool_input": {"file_path": rel_path}}
    reason = g.decide(data, sock_dir, proc, me)
    assert reason is not None
    assert str(other_checkout.resolve()) in reason
    assert str(other_pid) in reason


def test_notebook_path_checked_like_file_path(env):
    proc = env["proc"]
    sock_dir = env["sock_dir"]
    me = env["me"]
    own_checkout = env["own_checkout"]
    tmp_path = env["tmp_path"]

    other_checkout = make_checkout(tmp_path / "other_repo")
    nb_file = other_checkout / "analysis.ipynb"
    nb_file.touch()

    other_pid = 20
    make_proc_entry(proc, other_pid, parent_pid=1, cmdline=b"claude\0", cwd=other_checkout)
    make_socket(sock_dir, other_pid)

    data = {"cwd": str(own_checkout), "tool_input": {"notebook_path": str(nb_file)}}
    reason = g.decide(data, sock_dir, proc, me)
    assert reason is not None
    assert str(other_checkout.resolve()) in reason
    assert str(other_pid) in reason


def test_main_cli_behavior(env, capsys):
    proc = env["proc"]
    sock_dir = env["sock_dir"]
    me = env["me"]
    own_checkout = env["own_checkout"]
    tmp_path = env["tmp_path"]

    other_checkout = make_checkout(tmp_path / "other_repo")
    target_file = other_checkout / "file.py"
    target_file.touch()

    other_pid = 20
    make_proc_entry(proc, other_pid, parent_pid=1, cmdline=b"claude\0", cwd=other_checkout)
    make_socket(sock_dir, other_pid)

    # Deny
    deny_payload = json.dumps({
        "cwd": str(own_checkout),
        "tool_name": "Edit",
        "tool_input": {"file_path": str(target_file)},
    })
    rc = g.main(io.StringIO(deny_payload), sock_dir=sock_dir, proc=proc, me=me)
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    out_obj = json.loads(captured.out)
    assert out_obj["hookSpecificOutput"]["permissionDecision"] == "deny"

    # Allow
    allow_payload = json.dumps({
        "cwd": str(own_checkout),
        "tool_name": "Edit",
        "tool_input": {"file_path": str(own_checkout / "file.py")},
    })
    rc = g.main(io.StringIO(allow_payload), sock_dir=sock_dir, proc=proc, me=me)
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

    # Invalid JSON
    rc = g.main(io.StringIO("not valid json {"), sock_dir=sock_dir, proc=proc, me=me)
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_missing_socket_dir_allowed(env):
    proc = env["proc"]
    me = env["me"]
    own_checkout = env["own_checkout"]
    tmp_path = env["tmp_path"]

    other_checkout = make_checkout(tmp_path / "other_repo")
    target_file = other_checkout / "file.py"
    target_file.touch()

    missing_sock_dir = tmp_path / "nonexistent_socks"
    assert not missing_sock_dir.exists()

    data = {"cwd": str(own_checkout), "tool_input": {"file_path": str(target_file)}}
    reason = g.decide(data, missing_sock_dir, proc, me)
    assert reason is None

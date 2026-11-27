"""Behaviour matrix for hooks/discipline/delete-guard.sh (+ delete_guard.py).

The incident it exists for (2026-11-27): `just vm-destroy rhcsa1` ran
`virsh undefine --remove-all-storage`, which deleted the RHEL DVD ISO attached to
the VM. test_incident_* replay that exact shape.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GUARD = REPO / "hooks" / "discipline" / "delete-guard.sh"
HOME = os.path.expanduser("~")
BASH = shutil.which("bash") or "/bin/bash"


def run(cmd: str, tmp_path: Path, cwd: str | None = None, env: dict | None = None):
    payload = json.dumps({"session_id": "sess-del", "cwd": cwd or str(REPO),
                          "tool_input": {"command": cmd}})
    e = {**os.environ, "DELETE_GUARD_LOG": str(tmp_path / "hook-blocks.log"), **(env or {})}
    return subprocess.run([BASH, str(GUARD)], input=payload, capture_output=True,
                          text=True, env=e, timeout=30)


def blocked(r) -> bool:
    return r.returncode == 2


@pytest.fixture
def lab(tmp_path):
    """A repo whose justfile recipe runs a script holding --remove-all-storage,
    the shape of rhcsa-lab before its fix (5ed0cea)."""
    d = tmp_path / "lab"
    (d / "scripts").mkdir(parents=True)
    (d / ".git").mkdir()
    (d / "scripts" / "vm.sh").write_text(
        "#!/bin/bash\n# destroy the VM\nvirsh undefine \"$1\" --remove-all-storage\n")
    (d / "scripts" / "safe.sh").write_text(
        "#!/bin/bash\n# Never --remove-all-storage: it deletes the ISO.\n"
        "virsh undefine \"$1\" --storage vda\n")
    (d / "justfile").write_text(
        "vm-destroy name:\n    bash scripts/vm.sh {{name}}\n\n"
        "safe-destroy name:\n    bash scripts/safe.sh {{name}}\n\n"
        "test:\n    echo ok\n")
    return d


BLOCK = [
    "virsh -c qemu:///system undefine rhcsa1 --remove-all-storage",
    "virsh undefine rhcsa1 --wipe-storage",
    "virsh vol-delete rhcsa1.qcow2 --pool default",
    "virsh pool-delete isos",
    "rm -rf ~/isos",
    "rm -f ~/isos/rhel-10.3-x86_64-dvd.iso",
    "rm -rf $HOME/Downloads",
    "rm -rf /opt/lib/libvirt/images/win10.qcow2",
    'rm -rf "$work"',
    "rm -rf .git",
    "cd ~ && rm -rf isos",
    "cd /opt && rm -rf proj",
    "sudo rm -rf /var/lib/libvirt/images/x",
    "unlink ~/notes.txt",
    "shred -u ~/secret.txt",
    "git reset --hard origin/main",
    "git -C /opt/proj/x reset --hard",
    "git clean -fdx",
    "git clean -f",
    "docker compose down -v",
    "docker volume rm gitea_data",
    "docker system prune -af",
    "podman volume prune",
    "sudo dd if=x.iso of=/dev/sdb bs=4M",
    "sudo mkfs.ext4 /dev/sdb1",
    "wipefs -a /dev/sdb",
    'find ~/Downloads -name "*.iso" -delete',
    "find /opt/proj -name x -exec rm -f {} +",
    'bash -c "rm -rf ~/stuff"',
    "ls; rm -rf ~/x",
    "true && rm -rf ~/x",
    # review 2026-11-27: a comment with an apostrophe crashed the tokenizer
    "# do not clean it's\ndocker volume prune -f",
    "# it's\ngit clean -fdx",
    "# it's\ndd if=/dev/zero of=/dev/sda",
    "# it's\nfind /var -delete",
    "rm -rf ../.. # don't",
    # compound commands and wrappers with option values
    "if true; then rm -rf ~/x; fi",
    "for f in a; do rm -rf ~/x; done",
    "{ rm -rf ~/x; }",
    "! rm -rf ~/x",
    "echo $(rm -rf ~/x)",
    "echo `rm -rf ~/x`",
    "ls | xargs rm -rf",
    "find . -name x -print0 | xargs -0 rm -f",
    "sudo -u root rm -rf ~/x",
    "busybox rm -rf ~/x",
    "docker-compose down -v",
    "eval 'rm -rf ~/x'",
    "env -C ~ rm -rf x",
    # find with leading options; globs and braces
    "find -L ~/x -delete",
    "find -H ~ -name x -delete",
    "rm -rf {~/x,/tmp/y}",
    "rm -rf /tmp/{a,../home/bill/x}",
    "rm -rf */../../victim",
    "rm -rf .*",
    "rm -rf .git*",
    "rm -rf .[a-z]*",
    "pushd ~/Documents >/dev/null && rm -rf *",
    "cd - && rm -rf x",
    # re-review 2026-11-27
    "docker compose -f a.yml down -v",
    "docker-compose -f a.yml -p x down -v",
    "docker compose --file a.yml down --volumes",
    "docker compose down -fv",
    "docker compose rm -fsv",
    "setsid rm -rf ~/x",
    "flock /tmp/l rm -rf ~/x",
    "watch -n 5 rm -rf ~/x",
    "su -c 'rm -rf ~/x'",
    "case x in x) rm -rf ~/x;; esac",
    "git checkout -f main",
    "git switch --discard-changes main",
    "git stash clear",
    "sgdisk --zap-all /dev/sda",
    # same-line variables that point outside
    "M=$HOME/.uncle-j-memory/memory; T=$M/vault; rm -rf \"$T\"",
]

ALLOW = [
    "virsh undefine rhcsa1 --storage /var/lib/libvirt/images/rhcsa1.qcow2",
    "virsh list --all",
    "rm -rf build node_modules",
    "rm -rf /tmp/foo; ls",
    "rm -f x.txt 2>/dev/null",
    "rm -rf hooks/../build",
    "rm -rf ./*",
    "rm -rf /tmp/claude-1000/scratch/out",
    "git reset --soft HEAD~1",
    "git reset HEAD file.txt",
    "git clean -nd",
    "git clean -fdn",
    "docker compose down",
    "docker volume ls",
    "dd if=/dev/zero of=/tmp/img bs=1M count=1",
    "dd if=/dev/urandom of=/dev/null count=1",
    'find . -name "*.pyc" -delete',
    "find /tmp/x -type f -delete",
    'echo "rm -rf ~"',
    "git commit -F - <<EOF\nnote: never run rm -rf ~ or --remove-all-storage\nEOF",
    'grep -n "remove-all-storage" scripts/vm.sh',
    "ls -la ~/isos",
    "",
    # bench 2026-11-27: same-line variables and mktemp pointing into temp dirs
    "S=/tmp/claude-1000/x/scratchpad/pages; rm -rf $S; mkdir -p $S",
    "S=/tmp/claude-1000/x/scratchpad; rm -rf \"$S/ci\" && mkdir -p $S/ci",
    "set -e; d=$(mktemp -d); echo hi > \"$d/f\"; rm -rf \"$d\"",
    "W=$(mktemp -d); trap 'rm -rf \"$W\"' EXIT; ls $W",
    "S=/tmp/claude-1000/x; docker compose -p dbg --project-directory $S -f $S/compose.yml down -v",
    "docker volume prune --help",
    "# it's a comment\nls -la",
    "echo 'it''s' # fine",
    "if true; then rm -rf build; fi",
    "for f in a b; do rm -f /tmp/$f.txt; done",
    "rm -rf /tmp/{a,b}",
    "echo ${#arr[@]} # count",
    "S=/tmp/claude-1000/x/lab; rm -rf \"${S:?}\"/out",
    "S=/tmp/claude-1000/x; D=$(mktemp -d -p \"$S\"); rm -rf \"$D\"",
    "rm -rf /tmp/tmp.*/2026111?.json",
    "docker compose -f /tmp/claude-1000/x/compose.yml down -v",
    "docker compose ps -v",
    "git checkout main",
    "git stash list",
    "git worktree remove .claude/worktrees/x",
    "git worktree remove --force .claude/worktrees/x",  # routine post-merge cleanup (replay: 63/30 days)
    "case x in x) echo hi;; esac",
]


@pytest.mark.parametrize("cmd", BLOCK)
def test_blocks(cmd, tmp_path):
    r = run(cmd, tmp_path)
    assert blocked(r), f"not blocked: {cmd!r} stderr={r.stderr!r}"
    assert "delete-guard" in r.stderr and "DELETE_OK" in r.stderr


@pytest.mark.parametrize("cmd", ALLOW)
def test_allows(cmd, tmp_path):
    r = run(cmd, tmp_path)
    assert not blocked(r), f"blocked: {cmd!r} stderr={r.stderr!r}"


def test_incident_direct_virsh_names_the_iso_risk(tmp_path):
    r = run("virsh -c qemu:///system undefine rhcsa1 --snapshots-metadata --remove-all-storage", tmp_path)
    assert blocked(r) and "ISO" in r.stderr and "--storage" in r.stderr


def test_incident_just_recipe_running_script_is_blocked(lab, tmp_path):
    r = run("just vm-destroy rhcsa1", tmp_path, cwd=str(lab))
    assert blocked(r), r.stderr
    assert "remove-all-storage" in r.stderr and "vm.sh" in r.stderr


def test_just_recipe_from_subdir_resolves_scripts(lab, tmp_path):
    (lab / "docs").mkdir()
    r = run("just vm-destroy rhcsa1", tmp_path, cwd=str(lab / "docs"))
    assert blocked(r), r.stderr


def test_fixed_recipe_with_named_disks_passes(lab, tmp_path):
    """The fixed vm.sh mentions --remove-all-storage only in a comment."""
    assert not blocked(run("just safe-destroy rhcsa1", tmp_path, cwd=str(lab)))


def test_harmless_recipes_and_listing_pass(lab, tmp_path):
    for cmd in ("just test", "just --list", "just --show vm-destroy"):
        assert not blocked(run(cmd, tmp_path, cwd=str(lab))), cmd


def test_script_run_directly_is_scanned(lab, tmp_path):
    assert blocked(run("bash scripts/vm.sh rhcsa1", tmp_path, cwd=str(lab)))
    assert blocked(run("./scripts/vm.sh rhcsa1", tmp_path, cwd=str(lab)))
    assert not blocked(run("bash scripts/safe.sh rhcsa1", tmp_path, cwd=str(lab)))


def test_just_options_overrides_and_default_recipe(lab, tmp_path):
    for cmd in ("just -q vm-destroy x", "just --yes vm-destroy x", "just --justfile=justfile vm-destroy x",
                "just foo=1 vm-destroy x", f"just -f {lab}/justfile vm-destroy x"):
        assert blocked(run(cmd, tmp_path, cwd=str(lab))), cmd
    (lab / "justfile").write_text("default: wrap\n\nwrap: _inner\n\n_inner:\n    git reset --hard\n")
    assert blocked(run("just", tmp_path, cwd=str(lab)))          # bare just runs the default
    assert blocked(run("just default", tmp_path, cwd=str(lab)))  # through two dependencies


def test_bash_options_before_the_script(lab, tmp_path):
    for cmd in ("bash -o pipefail scripts/vm.sh x", "bash -e -o pipefail scripts/vm.sh x",
                "source scripts/vm.sh", ". scripts/vm.sh", "sh < scripts/vm.sh", "bash <scripts/vm.sh"):
        assert blocked(run(cmd, tmp_path, cwd=str(lab))), cmd


def test_destructive_strings_as_data_are_not_scanned(tmp_path):
    """Python files and the guard's own files hold these strings as data."""
    for cmd in ("bash hooks/discipline/delete-guard.sh </dev/null", "python3 tests/test_delete_guard.py",
                "./tests/test_delete_guard.py"):
        assert not blocked(run(cmd, tmp_path)), cmd


def test_symlink_out_of_the_repo_is_followed(lab, tmp_path):
    outside = tmp_path / "precious"
    outside.mkdir()
    (lab / "link").symlink_to(Path.home())
    assert blocked(run("rm -rf link/x", tmp_path, cwd=str(lab)))
    assert blocked(run("rm -rf link/*", tmp_path, cwd=str(lab)))


def test_repo_root_rules_use_the_command_cwd(lab, tmp_path):
    assert not blocked(run("rm -rf build", tmp_path, cwd=str(lab)))
    assert blocked(run("rm -rf build", tmp_path, cwd=HOME))  # ~/build is not a repo


def test_delete_ok_prefix_allows_and_logs(tmp_path):
    r = run('DELETE_OK="old scratch disk; William approved" virsh vol-delete x.qcow2 --pool default', tmp_path)
    assert not blocked(r), r.stderr
    log = (tmp_path / "hook-blocks.log").read_text()
    assert "ALLOWED delete-guard" in log and "William approved" in log and "session=sess-del" in log


def test_delete_ok_covers_only_its_own_command(tmp_path):
    r = run('DELETE_OK="x" virsh vol-delete a --pool p; rm -rf ~/isos', tmp_path)
    assert blocked(r)


def test_empty_delete_ok_does_not_allow(tmp_path):
    assert blocked(run('DELETE_OK="" rm -rf ~/isos', tmp_path))


def test_block_is_logged_on_one_line(tmp_path):
    run("rm -rf ~/isos\nls", tmp_path)
    lines = (tmp_path / "hook-blocks.log").read_text().splitlines()
    assert len(lines) == 1 and "BLOCKED delete-guard" in lines[0] and "session=sess-del" in lines[0]


def test_unparseable_command_falls_back_to_regex(tmp_path):
    assert blocked(run("rm -rf ~/isos 'unbalanced", tmp_path))
    assert not blocked(run("echo 'unbalanced", tmp_path))


def test_judge_crash_falls_back_to_regex(tmp_path):
    """No python3 on PATH: the wrapper's bash regex still blocks the obvious forms."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("jq", "cat", "mktemp", "rm", "grep", "date", "tr", "head", "wc", "iconv", "find", "mkdir", "rmdir", "mv", "readlink", "dirname"):
        src = subprocess.run(["bash", "-c", f"command -v {tool}"], capture_output=True, text=True).stdout.strip()
        if src:
            (bindir / tool).symlink_to(src)
    env = {"PATH": str(bindir)}
    assert blocked(run("virsh undefine x --remove-all-storage", tmp_path, env=env))
    assert not blocked(run("ls -la", tmp_path, env=env))

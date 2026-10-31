"""Behaviour matrix for hooks/pre-mortem-guard/token-guard.sh.

The guard stops any way of creating a pre-mortem clearance token except the
skill's call to write-clearance-token.sh. The BLOCK cases matter more than the
ALLOW ones: a missed write is a bypass of the pre-mortem gate.

The ALLOW cases come from state/hook-blocks.log (2026-06 to 2026-10): about a
dozen blocks that only READ a token (`cat`, `ls`, python `open()`), caught
because `cat` was on the write list and `.*` let a match run across `;`/`&&`/`|`
into another command. (`.*` stays: see test_quoted_separator_does_not_hide_a_write.)
UNCLE_J_PROJ_ROOT points the log at tmp_path.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "hooks" / "pre-mortem-guard" / "token-guard.sh"
WRITER = REPO_ROOT / "hooks" / "pre-mortem-guard" / "write-clearance-token.sh"
TOK = "/tmp/premortem-cleared-0000aaaa-1111"


def run(command: str, tmp_path: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    (tmp_path / "Uncle-J-s-Refinery" / "state").mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "UNCLE_J_PROJ_ROOT": str(tmp_path), **(env_extra or {})}
    payload = {"tool_input": {"command": command}, "session_id": "sess-t"}
    return subprocess.run(["bash", str(GUARD)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=30)


def denied(res: subprocess.CompletedProcess) -> bool:
    if not res.stdout.strip():
        return False
    out = json.loads(res.stdout)
    return out["hookSpecificOutput"]["permissionDecision"] == "deny"


def log_lines(tmp_path: Path) -> list[str]:
    p = tmp_path / "Uncle-J-s-Refinery" / "state" / "hook-blocks.log"
    return p.read_text(encoding="utf-8").splitlines() if p.exists() else []


BLOCK = [
    f"touch {TOK}",
    f"printf 'PRE-MORTEM-COMPLETE\\n' > {TOK}",
    f"echo '{{\"ts\": 1}}' >> {TOK}",
    f"cat > {TOK} <<'EOF'\nx\nEOF",
    f"echo x | tee {TOK}",
    f"cp /tmp/a {TOK}",
    f"dd if=/dev/zero of={TOK} count=1",
    f"install -m 600 /tmp/a {TOK}",
    f"rsync /tmp/a {TOK}",
    f"python3 -c \"open('{TOK}','w').write('x')\"",
    f"python3 -c \"import pathlib;pathlib.Path('{TOK}').write_text('x')\"",
    f"node -e \"require('fs').writeFileSync('{TOK}','x')\"",
    f"perl -e 'open F,\">{TOK}\"'",
    f"openssl rand -out {TOK} 8",
    f"ls; touch {TOK}",
    f"cd /tmp && :> {TOK}",
    # a fake writer at another path is not the authorized script
    f"bash /tmp/write-clearance-token.sh {TOK}; touch {TOK}",
]

ALLOW = [
    f"cat {TOK}",
    f"ls -la {TOK} 2>&1; cat {TOK} 2>&1; echo; echo \"now epoch: $(date +%s)\"",
    "cat /home/x/.claude/hooks/pre-mortem-guard/write-clearance-token.sh 2>/dev/null | head -30;"
    " ls /tmp/premortem-cleared-b67* 2>/dev/null && echo exists",
    "cat ~/.uncle-j-memory/memory/premortem-audit.md | grep -c X; ls /tmp/premortem-cleared-* 2>/dev/null",
    f"python3 -c \"import json,time;d=json.load(open('{TOK}'));print(d['ts'])\"",
    f"ls -l {TOK} 2>&1 | cut -c1-80; date +%s; cat {TOK} 2>/dev/null",
    "echo hello > /tmp/other-file",
    "git status",
]


@pytest.mark.parametrize("cmd", BLOCK)
def test_token_writes_are_blocked(cmd, tmp_path):
    res = run(cmd, tmp_path)
    assert denied(res), f"not blocked: {cmd!r}\n{res.stdout}{res.stderr}"
    lines = log_lines(tmp_path)
    assert len(lines) == 1 and "BLOCKED token-guard direct-token-write" in lines[0]
    assert "session=sess-t" in lines[0]


@pytest.mark.parametrize("cmd", ALLOW)
def test_token_reads_are_allowed(cmd, tmp_path):
    res = run(cmd, tmp_path)
    assert not denied(res), f"blocked: {cmd!r}"
    assert res.returncode == 0
    assert log_lines(tmp_path) == []


def test_authorized_writer_by_repo_path(tmp_path):
    assert not denied(run(f"bash {WRITER} {TOK}", tmp_path))


def test_authorized_writer_through_symlink(tmp_path):
    """The skill calls ~/.claude/hooks/pre-mortem-guard/write-clearance-token.sh, a
    symlink into this repo. Identity, not spelling, decides, so a replay under
    another HOME still allows it."""
    link_dir = tmp_path / "home" / ".claude" / "hooks" / "pre-mortem-guard"
    link_dir.mkdir(parents=True)
    (link_dir / "write-clearance-token.sh").symlink_to(WRITER)
    assert not denied(run(f"bash {link_dir}/write-clearance-token.sh {TOK}", tmp_path))
    assert not denied(run(f"bash ~/.claude/hooks/pre-mortem-guard/write-clearance-token.sh {TOK}",
                          tmp_path, {"HOME": str(tmp_path / "home")}))


def test_authorized_call_does_not_unlock_the_rest_of_the_command(tmp_path):
    """The old guard exited 0 as soon as the writer's call appeared anywhere."""
    assert denied(run(f"bash {WRITER} {TOK} && touch {TOK}", tmp_path))
    assert denied(run(f"echo x > {TOK}; bash {WRITER} {TOK}", tmp_path))


def test_copy_of_writer_elsewhere_is_not_authorized(tmp_path):
    fake = tmp_path / "write-clearance-token.sh"
    fake.write_text("#!/bin/bash\n")
    # running a non-authorized script is not itself a token write the guard can see,
    # but it must not unlock a direct write in the same command
    assert denied(run(f"bash {fake} {TOK} && touch {TOK}", tmp_path))


@pytest.mark.parametrize("cmd", [
    "rm ~/.claude/hooks/discipline/grep-guard.sh",
    "rm -f /home/x/.claude/hooks/pre-mortem-guard/token-guard.sh",
    "cd /tmp && rm -rf ~/.claude/hooks/scan-secrets/",
])
def test_guard_deletion_blocked(cmd, tmp_path):
    res = run(cmd, tmp_path)
    assert denied(res)
    assert "guard-deletion-attempt" in log_lines(tmp_path)[0]


def test_quoted_separator_does_not_hide_a_write(tmp_path):
    """Patterns span separators on purpose: a segment split can't see quotes."""
    assert denied(run(f"touch ';' {TOK}", tmp_path))
    assert denied(run(f"rm \"a|b\" ~/.claude/hooks/discipline/grep-guard.sh", tmp_path))


def test_no_command_is_a_noop(tmp_path):
    env = {**os.environ, "UNCLE_J_PROJ_ROOT": str(tmp_path)}
    res = subprocess.run(["bash", str(GUARD)], input=json.dumps({"tool_input": {}}),
                         capture_output=True, text=True, env=env, timeout=30)
    assert res.returncode == 0 and res.stdout == ""

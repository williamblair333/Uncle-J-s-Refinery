"""Tests for hooks/discipline/credential-guard.sh (PreToolUse, all tools).

Each case pipes a real hook payload into the script. UNCLE_J_PROJ_ROOT points the
block log at a temp dir, so test denials never reach the live state/hook-blocks.log.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
HOOK = _REPO / "hooks" / "discipline" / "credential-guard.sh"
SETTINGS_COMMAND = f"bash {HOOK} || exit 1"  # the shape install-reliability.sh wires

pytestmark = pytest.mark.skipif(not shutil.which("jq"), reason="hook needs jq")


def run(tool, tool_input, tmp_path, command=None):
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "session_id": "test"})
    env = {**os.environ, "UNCLE_J_PROJ_ROOT": str(tmp_path)}
    return subprocess.run(command or ["bash", str(HOOK)], input=payload, capture_output=True,
                          text=True, env=env, timeout=20)


def denied(proc):
    if proc.returncode != 0 or not proc.stdout.strip():
        return False
    return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


BLOCK = [
    ("Read", {"file_path": "/home/bill/.ssh/id_ed25519"}),
    ("Read", {"file_path": "/home/bill/.ssh/id_ed25519.pub"}),  # BLOCK_WHOLE_SSH
    ("Read", {"file_path": "/home/bill/.ssh/known_hosts"}),
    ("Read", {"file_path": "~/.aws/credentials"}),
    ("Read", {"file_path": "/home/bill/.claude/.credentials.json"}),
    ("Read", {"file_path": "/home/bill/.claude.json"}),
    ("Read", {"file_path": "/home/bill/.config/gh/hosts.yml"}),
    ("Read", {"file_path": "/opt/proj/Uncle-J-s-Refinery/.env"}),
    ("Read", {"file_path": "/srv/app/.env.production"}),
    ("Read", {"file_path": "/etc/shadow"}),
    ("Read", {"file_path": "/etc/ssh/ssh_host_ed25519_key"}),
    ("Read", {"file_path": "/proc/self/environ"}),
    ("Read", {"file_path": "C:\\Users\\bill\\.ssh\\id_rsa"}),
    ("Read", {"file_path": "/home/bill/certs/server.key"}),
    ("Read", {"file_path": "/home/bill/vault.kdbx"}),
    ("Edit", {"file_path": "/home/bill/.netrc", "old_string": "a", "new_string": "b"}),
    ("Write", {"file_path": "/home/bill/.gnupg/gpg.conf", "content": "x"}),
    ("Grep", {"pattern": "PRIVATE", "path": "/home/bill/.ssh"}),
    ("Glob", {"pattern": "/home/bill/.aws/*"}),
    ("NotebookEdit", {"notebook_path": "/root/nb.ipynb", "new_source": "x"}),
    ("Bash", {"command": "cat ~/.ssh/id_rsa"}),
    ("Bash", {"command": "cat $HOME/.netrc"}),
    ("Bash", {"command": "sudo cat /etc/shadow | head"}),
    ("Bash", {"command": "source .env && echo $TOKEN"}),
    ("Bash", {"command": "ls /root"}),
    ("Bash", {"command": "tar czf /tmp/k.tgz ~/.gnupg"}),
    ("Bash", {"command": "cp ~/.docker/config.json /tmp/"}),
    ("mcp__ask_local__summarize_local", {"path": "/home/bill/.kube/config"}),
    ("mcp__live_preview__preview_publish", {"project": "p", "session": "s", "label": "x",
                                            "images": ["/tmp/a.png", "/home/bill/.ssh/id_rsa"]}),
    ("mcp__jcodemunch__index_folder", {"path": "/home/bill/.password-store"}),
]

ALLOW = [
    # The .pub exception is for public keys elsewhere; ~/.ssh as a whole stays closed
    # (known_hosts and config map the hosts), see BLOCK_WHOLE_SSH below.
    ("Read", {"file_path": "/opt/proj/deploy/keys/id_ed25519.pub"}),
    ("Read", {"file_path": "/etc/ssh/ssh_host_ed25519_key.pub"}),
    ("Read", {"file_path": "/opt/proj/app/.env.example"}),
    ("Read", {"file_path": "/opt/proj/app/.env.template"}),
    ("Read", {"file_path": "/etc/passwd"}),
    ("Read", {"file_path": "/opt/proj/Uncle-J-s-Refinery/docs/ssh-notes.md"}),
    ("Read", {"file_path": "/opt/proj/app/.dockerignore"}),
    ("Read", {"file_path": "/opt/proj/app/.environment.md"}),
    ("Read", {"file_path": "/opt/proj/app/src/root/handler.py"}),
    # Contents are never inspected: writing code that mentions the paths is fine.
    ("Write", {"file_path": "/opt/proj/x/test_secrets.py", "content": "BAD = '~/.ssh/id_rsa'"}),
    ("Edit", {"file_path": "/opt/proj/x/a.py", "old_string": "a", "new_string": "open('/etc/shadow')"}),
    ("Grep", {"pattern": "\\.ssh|\\.env", "path": "/opt/proj/x"}),
    ("Bash", {"command": "python3 -c 'import os; print(os.environ.get(\"HOME\"))'"}),
    ("Bash", {"command": "node -e 'console.log(process.env.HOME)'"}),
    ("Bash", {"command": "jq '.key' data.json && jq 'to_entries[].key' x.json"}),
    ("Bash", {"command": "printf 'protocol=http\\nhost=10.0.0.100:3000\\n\\n' | git credential fill"}),
    ("Bash", {"command": "ls /opt/root && cat /tmp/my_id_rsa_notes.txt"}),
    ("Bash", {"command": "git log --oneline -3"}),
    ("mcp__jcodemunch__search_text", {"repo": "r", "query": ".ssh"}),
    ("TodoWrite", {"todos": [{"content": "rotate ~/.ssh keys", "status": "pending"}]}),
    ("Read", {}),
]


@pytest.mark.parametrize("tool,tool_input", BLOCK, ids=[f"{t}:{json.dumps(i)[:60]}" for t, i in BLOCK])
def test_credential_access_is_denied(tool, tool_input, tmp_path):
    proc = run(tool, tool_input, tmp_path)
    assert denied(proc), proc.stdout + proc.stderr


@pytest.mark.parametrize("tool,tool_input", ALLOW, ids=[f"{t}:{json.dumps(i)[:60]}" for t, i in ALLOW])
def test_ordinary_calls_pass(tool, tool_input, tmp_path):
    proc = run(tool, tool_input, tmp_path)
    assert proc.returncode == 0 and proc.stdout.strip() == "", proc.stdout + proc.stderr


def test_deny_reason_names_the_match_and_logs_one_line(tmp_path):
    (tmp_path / "Uncle-J-s-Refinery" / "state").mkdir(parents=True)
    proc = run("Bash", {"command": "cat ~/.ssh/id_rsa\necho done"}, tmp_path)
    reason = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert ".ssh" in reason and "!" in reason
    log = (tmp_path / "Uncle-J-s-Refinery" / "state" / "hook-blocks.log").read_text().splitlines()
    assert len(log) == 1 and "credential-guard tool=Bash" in log[0] and "session=test" in log[0]


def test_script_parses():
    assert subprocess.run(["bash", "-n", str(HOOK)]).returncode == 0


def test_broken_guard_fails_open_never_blocks(tmp_path):
    """The settings shape `bash <hook> || exit 1` turns a syntax error (bash exit 2 = block)
    or a missing script (127) into exit 1, which Claude Code reports without blocking."""
    broken = tmp_path / "broken.sh"
    broken.write_text("if then fi\n")
    for target in (broken, tmp_path / "missing.sh"):
        proc = run("Read", {"file_path": "/home/bill/.ssh/id_rsa"}, tmp_path,
                   command=["sh", "-c", f"bash {target} || exit 1"])
        assert proc.returncode == 1


def test_settings_shape_still_denies(tmp_path):
    proc = run("Read", {"file_path": "/home/bill/.ssh/id_rsa"}, tmp_path,
               command=["sh", "-c", SETTINGS_COMMAND])
    assert denied(proc)


def test_malformed_payload_fails_open(tmp_path):
    env = {**os.environ, "UNCLE_J_PROJ_ROOT": str(tmp_path)}
    proc = subprocess.run(["sh", "-c", SETTINGS_COMMAND], input="not json", capture_output=True,
                          text=True, env=env, timeout=20)
    assert proc.returncode in (0, 1) and proc.stdout.strip() == ""

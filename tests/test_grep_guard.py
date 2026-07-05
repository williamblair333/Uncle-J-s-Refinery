"""
Behaviour matrix for hooks/discipline/grep-guard.sh.

The guard routes SOURCE-CODE exploration to jcodemunch (token + accuracy economy).
It must DENY reading/searching repo source code, and ALLOW everything else —
crucially: stdin pipes, log/state/tmp/proc targets, non-source files, in-place
edits, and all output redirections / heredocs (writes, incl. the pre-mortem
audit sink and clearance-token flows). False positives strangle normal work, so
the ALLOW cases are as important as the DENY cases.
"""
import json
import os
import subprocess

import pytest

HOOK = os.path.join(os.path.dirname(__file__), "..", "hooks", "discipline", "grep-guard.sh")


def _denied(cmd: str) -> bool:
    """Run the guard with a fake PreToolUse payload; True iff it denies."""
    payload = json.dumps({"tool_input": {"command": cmd}, "session_id": "test"})
    r = subprocess.run(["bash", HOOK], input=payload, capture_output=True, text=True)
    return '"deny"' in r.stdout.replace(" ", "")


# ── DENY: reading/searching repo source for exploration ──────────────────────

DENY_CASES = [
    "grep -rn foo scripts/",                              # legacy recursive on repo dir
    "grep foo scripts/telegram-gateway-poll.sh",         # source file arg, non-recursive
    "grep -i needle scripts/lib/tg_security.py",
    "cat scripts/lib/tg_security.py",                     # cat a source file
    "sed -n '1,20p' scripts/telegram-gateway-poll.sh",   # sed read range
    "head -50 scripts/lib/tg_security.py",
    "tail -20 scripts/telegram-gateway-poll.sh",
    "cat scripts/lib/tg_security.py | grep build_claude", # cat reads source even though grep is piped
    "rg build_claude_argv",                              # ripgrep recursive in cwd (repo)
]


@pytest.mark.parametrize("cmd", DENY_CASES)
def test_guard_denies_source_exploration(cmd):
    assert _denied(cmd) is True, f"expected DENY: {cmd}"


# ── ALLOW: everything that is not source exploration ─────────────────────────

ALLOW_CASES = [
    "crontab -l | grep -i memweave",                     # stdin pipe, no source file
    "ps aux | grep python",
    "echo hello | grep h",
    "grep -i foo state/telegram-gateway.log",            # .log target
    "grep -rn pattern /var/log/syslog",                  # /var/log
    "tail -f state/memweave-sync.log",                   # log tail
    "grep needle /tmp/scratch.txt",                      # /tmp
    "cat /proc/sys/fs/inotify/max_user_watches",         # /proc
    "cat /etc/hostname",                                 # not source ext
    "grep TELEGRAM_BOT_TOKEN .env",                      # .env not source, jcode can't read it
    "git commit -m 'fix things'",                        # no read/search tool on source
    "ls scripts/",                                        # listing, not reading
    "sed -i 's/a/b/' scripts/telegram-gateway-poll.sh",  # in-place EDIT (write), not a read
    "printf 'x' > scripts/new-thing.sh",                 # redirect WRITE to a source path
    "cat >> ~/.uncle-j-memory/memory/premortem-audit.md <<'PM_EOF'",  # audit-sink heredoc write
    "cat >> /opt/proj/Uncle-J-s-Refinery/CHANGELOG.md <<'EOF'",       # heredoc append write
    "grep foo /usr/lib/python3.11/json/decoder.py",      # absolute source OUTSIDE repo → jcode can't help
    # ── 2026-07-05 false-positive regressions (real blocked commands from hook-blocks.log) ──
    # grep PATTERN arg ending in .sh is not a file operand; segment reads stdin
    'cat /home/bill/.local/bin/*.sh /home/bill/.local/bin/git-autobackup/* 2>/dev/null | grep -c "ytd\\.sh"',
    # hyphenated words ("-MORTEM", "-opt-proj-…", "ytd-angel-pr-pin") are not -r flags
    "grep -A4 '\\[PRE-MORTEM DECLINED\\]' ~/.uncle-j-memory/memory/premortem-audit.md 2>/dev/null | tail -20",
    "grep -n 'TOP PRIORITY' /home/bill/.claude/projects/-opt-proj-proj-fog-of-chess/memory/MEMORY.md",
    'grep -q "ytd-angel-pr-pin" /home/bill/.claude/projects/-home-bill--local-bin/memory/MEMORY.md',
    # recursive grep whose only target is absolute OUTSIDE the repo → jcode can't help
    'grep -rl "ytd.sh" /home/bill/.local/bin/ --include="*.sh" 2>/dev/null',
    # --include=*.sh is a filter flag, not a file being read
    "ps aux | grep --include=*.sh -i python",
    # sed script text is not a file operand
    "echo status | sed 's/foo.py/bar/'",
]


# ── DENY still holds where the loosened paths could over-reach ────────────────

DENY_REGRESSION_CASES = [
    "grep -r foo scripts/",                               # bare -r flag, relative repo dir
    "grep -rn foo .",                                     # recursive on cwd (repo)
    'grep "needle" scripts/lib/tg_security.py',           # pattern skipped, file arg still caught
    "sed '1,20p' scripts/telegram-gateway-poll.sh",       # sed script skipped, file still caught
    "grep -rn foo /opt/proj/Uncle-J-s-Refinery/scripts/", # recursive on absolute repo path
]


@pytest.mark.parametrize("cmd", DENY_REGRESSION_CASES)
def test_guard_still_denies_after_fp_narrowing(cmd):
    assert _denied(cmd) is True, f"expected DENY: {cmd}"


@pytest.mark.parametrize("cmd", ALLOW_CASES)
def test_guard_allows_non_source_and_writes(cmd):
    assert _denied(cmd) is False, f"expected ALLOW: {cmd}"


# ── Specific regression: the substring-exception must match the TARGET, not the
#    whole command. A recursive source grep with "state/" mentioned elsewhere
#    must still be DENIED. ──────────────────────────────────────────────────────

def test_substring_exception_does_not_leak_via_comment():
    assert _denied("grep -rn pattern scripts/ # see also state/notes") is True

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
import tempfile
import uuid

import pytest

HOOK = os.path.join(os.path.dirname(__file__), "..", "hooks", "discipline", "grep-guard.sh")
LIVE_LOG = "/opt/proj/Uncle-J-s-Refinery/state/hook-blocks.log"

# Keep test denials out of the live state/hook-blocks.log (1191 `session=test` lines
# had piled up there, which the weekly review had to filter by hand). The guard logs
# to <first existing projects root>/Uncle-J-s-Refinery/state/hook-blocks.log;
# UNCLE_J_PROJ_ROOT is tried first, so an EMPTY existing dir wins and the append
# fails silently (`|| true`). The extra root only widens the fallback in-repo set
# with a dir no test path lives under.
_LOG_SINK = tempfile.mkdtemp(prefix="grep-guard-test-")
ENV = {**os.environ, "UNCLE_J_PROJ_ROOT": _LOG_SINK}


def _denied(cmd: str, session: str = "test") -> bool:
    """Run the guard with a fake PreToolUse payload; True iff it denies."""
    payload = json.dumps({"tool_input": {"command": cmd}, "session_id": session})
    r = subprocess.run(["bash", HOOK], input=payload, capture_output=True, text=True, env=ENV)
    return '"deny"' in r.stdout.replace(" ", "")


def test_denials_do_not_reach_the_live_log():
    probe = f"isolation-probe-{uuid.uuid4().hex}"
    assert _denied("grep -rn foo scripts/", session=probe) is True
    if os.path.exists(LIVE_LOG):
        with open(LIVE_LOG, encoding="utf-8", errors="replace") as f:
            assert probe not in f.read(), "test denial was written to the live hook-blocks.log"


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
    # numeric-only pattern must not swallow the path operand (code-review finding)
    "grep -rl 500 /home/bill/.local/bin/",
    # --include=*.sh is a filter flag, not a file being read
    "ps aux | grep --include=*.sh -i python",
    # sed script text is not a file operand
    "echo status | sed 's/foo.py/bar/'",
    # ── 2026-08-13: `~`-prefixed source OUTSIDE the repo. The guard receives the RAW
    #    unexpanded command string, so `~` never arrives as `/`. Matching only /* denied
    #    these while the identical /home/bill/… spelling was allowed — same file, opposite
    #    verdict, purely on spelling. (Found while reviewing state/hook-blocks.log.)
    # (Was `~/.claude/hooks/pre-mortem-guard/surface-write-guard.sh` — but on this host
    #  that is a symlink INTO this repo, so the case pinned the symlink bypass itself.
    #  2026-10-22: symlinks now resolve; see the symlink tests at the bottom.)
    "grep -n foo ~/.local/bin/git-autobackup/backup.sh",
    "cat ~/.local/bin/git-autobackup/backup.sh",
    "sed -n '1,20p' ~/scratch/probe.py",
    "head -20 ~/.local/bin/ytd.sh",
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


# ── Log hygiene: one blocked command must produce exactly one log entry. ──────
#    `head -c` truncates BYTES, not lines, so an unsanitised multi-line $CMD wrote N
#    rows into state/hook-blocks.log and only the last carried `session=`. That broke
#    the one-entry-per-line parsing the weekly review depends on — 385 of 3452 lines
#    were continuation junk when this was found (2026-08-13).

def test_multiline_blocked_command_logs_exactly_one_line(tmp_path):
    root = tmp_path / "root"
    (root / "Uncle-J-s-Refinery" / "state").mkdir(parents=True)
    log = root / "Uncle-J-s-Refinery" / "state" / "hook-blocks.log"

    cmd = 'echo "=== one ==="\ngrep -rn needle scripts/\necho "=== two ==="'
    payload = json.dumps({"tool_input": {"command": cmd}, "session_id": "multiline-test"})
    env = {**os.environ, "UNCLE_J_PROJ_ROOT": str(root)}
    r = subprocess.run(
        ["bash", HOOK], input=payload, capture_output=True, text=True, env=env
    )

    # Guard the fixture itself: no deny means no log line, and the assertions below
    # would pass vacuously.
    assert '"deny"' in r.stdout.replace(" ", ""), f"fixture must deny; got {r.stdout!r}"

    lines = log.read_text().splitlines()
    assert len(lines) == 1, f"expected exactly 1 log entry, got {len(lines)}: {lines}"
    assert lines[0].endswith("session=multiline-test"), (
        f"session id must survive on the same line as the command: {lines[0]!r}"
    )


# ── "The repo" is the SESSION's repo, not every project under /opt/proj ─────────
#    (2026-10-16, weekly hook-blocks review.) REPO_ROOTS was the projects root, so a
#    Refinery session reading /opt/proj/voice-line sources was denied even though the
#    block message says source outside this repo is allowed. The guard now scopes to
#    the git toplevel of the hook payload's `cwd`; with no usable cwd it falls back to
#    the broad projects roots (fail closed).

REPO = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))


def _denied_in(cmd: str, cwd) -> bool:
    payload = {"tool_input": {"command": cmd}, "session_id": "test"}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    r = subprocess.run(["bash", HOOK], input=json.dumps(payload), capture_output=True, text=True,
                       env=ENV)
    return '"deny"' in r.stdout.replace(" ", "")


SESSION_REPO_ALLOW = [
    "grep -n listen /opt/proj/voice-line/scripts/dictate.sh",   # another project's source
    "sed -n '1,40p' /opt/proj/hearth/src/hearth/cli.py",
    "grep -rn dotenv /opt/proj/hearth/src/",                    # recursive, other project
]

SESSION_REPO_DENY = [
    f"cat {REPO}/scripts/referee.py",                           # this repo, absolute
    f"grep -rn foo {REPO}/scripts/",
    "grep -rn foo scripts/",                                    # relative → session repo
    "head -20 scripts/referee.py",
]


@pytest.mark.parametrize("cmd", SESSION_REPO_ALLOW)
def test_other_projects_source_allowed_from_this_session(cmd):
    assert _denied_in(cmd, REPO) is False, f"expected ALLOW: {cmd}"


@pytest.mark.parametrize("cmd", SESSION_REPO_DENY)
def test_session_repo_source_still_denied(cmd):
    assert _denied_in(cmd, REPO) is True, f"expected DENY: {cmd}"


@pytest.mark.parametrize("cwd", [None, "/nonexistent/dir"])
def test_no_usable_cwd_falls_back_to_projects_root(cwd):
    # Fail closed: without a session repo, every /opt/proj project counts as in-repo.
    assert _denied_in("cat /opt/proj/voice-line/scripts/stt.py", cwd) is True


def test_non_git_cwd_falls_back_to_projects_root(tmp_path):
    assert _denied_in("cat /opt/proj/voice-line/scripts/stt.py", tmp_path) is True


# ── Symlink / `..` resolution (2026-10-22, ROADMAP "grep-guard in_repo() symlink
#    bypass"). in_repo() was a literal string-prefix test, so repo source reached
#    through a home-dir symlink (~/.claude/hooks/discipline/grep-guard.sh -> this
#    repo) was allowed under either spelling, and a `..` hop through an allowed dir
#    (/tmp/../<repo>/x.py, scripts/hook-blocks/../x.py) matched ALLOWED_RE. Paths are
#    now judged on where they LAND (realpath -m), and the allow-list on the resolved
#    repo-relative remainder.

def _run(cmd: str, cwd=None, env=None) -> bool:
    payload = {"tool_input": {"command": cmd}, "session_id": "test"}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    r = subprocess.run(["bash", HOOK], input=json.dumps(payload), capture_output=True,
                       text=True, env=env or ENV)
    return '"deny"' in r.stdout.replace(" ", "")


@pytest.fixture
def fake_home(tmp_path):
    """A HOME whose ~/.claude/hooks/discipline links into this repo, as install does."""
    home = tmp_path / "home"
    (home / ".claude" / "hooks").mkdir(parents=True)
    os.symlink(os.path.join(REPO, "hooks", "discipline"), home / ".claude" / "hooks" / "discipline")
    os.symlink(os.path.join(REPO, "scripts"), tmp_path / "scripts-link")
    os.symlink(os.path.join(REPO, "scripts", "referee.py"), tmp_path / "notes.txt")
    (tmp_path / "outside.py").write_text("x = 1\n")
    return tmp_path, home, {**ENV, "HOME": str(home)}


def test_symlinked_repo_source_denied_by_tilde_spelling(fake_home):
    tmp, home, env = fake_home
    assert _run("grep -n deny ~/.claude/hooks/discipline/grep-guard.sh", REPO, env) is True
    assert _run("cat ~/.claude/hooks/discipline/push-guard.sh", REPO, env) is True


def test_symlinked_repo_source_denied_by_absolute_spelling(fake_home):
    tmp, home, env = fake_home
    assert _run(f"cat {home}/.claude/hooks/discipline/grep-guard.sh", REPO, env) is True
    # tmp_path lives under /tmp/ — an ALLOWED_RE location — so this also proves the
    # allow-list is judged after resolution, not on the literal /tmp/ spelling.
    assert _run(f"head -5 {tmp}/scripts-link/referee.py", REPO, env) is True


def test_symlinked_repo_source_denied_without_session_cwd(fake_home):
    # Fallback roots (/opt/proj…) must also be compared on the resolved spelling.
    tmp, home, env = fake_home
    if not REPO.startswith("/opt/proj/"):
        pytest.skip("repo not under a fallback projects root on this host")
    assert _run("cat ~/.claude/hooks/discipline/grep-guard.sh", None, env) is True


def test_extensionless_symlink_to_repo_source_denied(fake_home):
    tmp, home, env = fake_home
    assert _run(f"cat {tmp}/notes.txt", REPO, env) is True


def test_recursive_grep_through_symlinked_dir_denied(fake_home):
    tmp, home, env = fake_home
    assert _run("grep -rn foo ~/.claude/hooks/discipline/", REPO, env) is True
    assert _run(f"grep -rn foo {tmp}/scripts-link", REPO, env) is True


DOTDOT_DENY = [
    f"cat /tmp/..{REPO}/scripts/referee.py",                 # .. hop through /tmp/
    f"cat {REPO}/scripts/hook-blocks/../referee.py",          # .. hop through hook-blocks
    "cat scripts/hook-blocks/../referee.py",                  # same, relative
    "sed -n 1,5p state/../scripts/referee.py",                # .. hop through state/
    f"grep -rn foo {REPO}",                                   # repo root, no trailing slash
    "grep -rn foo scripts/ /tmp/",                            # one allowed operand no longer
    f"grep -rn foo /var/log/../..{REPO}/",                    #   clears the whole segment
    f"grep -rn foo {os.path.dirname(REPO)}/",                 # ancestor of the repo
]


@pytest.mark.parametrize("cmd", DOTDOT_DENY)
def test_dotdot_and_mixed_operand_bypasses_denied(cmd):
    assert _run(cmd, REPO) is True, f"expected DENY: {cmd}"


SYMLINK_ERA_ALLOW = [
    f"cat {REPO}/state/notes.py",                  # in-repo but an allowed location
    "cat ./state/x.py",
    "grep foo state/run.log",
    "grep -rn foo state/",
    "grep -r --include=*.log foo .",                # only .log files are read
    "grep -rn foo /var/log/",
    "ps aux | grep python",                         # stdin pipe (`grep -r` with no
                                                    #   operand walks cwd — denied, as before)
    "cat /etc/hostname",
    "grep -rn dotenv /opt/proj/hearth/src/",        # other project, session-scoped
]


@pytest.mark.parametrize("cmd", SYMLINK_ERA_ALLOW)
def test_resolution_keeps_legitimate_reads_allowed(cmd):
    assert _run(cmd, REPO) is False, f"expected ALLOW: {cmd}"


def test_rg_through_symlinked_dir_denied(fake_home):
    # tmp_path is under /tmp/; the old whole-command ALLOWED_RE test allowed this.
    tmp, home, env = fake_home
    assert _run(f"rg foo {tmp}/scripts-link", REPO, env) is True


RG_DENY = [
    "rg foo",                                  # cwd = repo
    "rg foo scripts/ /tmp/",                   # one allowed operand clears nothing
    "(rg foo scripts/)",
    "echo x && rg -e foo scripts/",
    "rg -g '*.py' foo .",
]

RG_ALLOW = [
    "ps aux | rg python",                      # stdin
    "rg foo /tmp/scratch.txt",
    "rg foo state/",
    "rg -e foo /var/log/syslog",
    "rg -g '*.log' foo .",
    "rg foo /opt/proj/hearth/src/",            # other project
]


@pytest.mark.parametrize("cmd", RG_DENY)
def test_rg_per_operand_denies(cmd):
    assert _run(cmd, REPO) is True, f"expected DENY: {cmd}"


@pytest.mark.parametrize("cmd", RG_ALLOW)
def test_rg_per_operand_allows(cmd):
    assert _run(cmd, REPO) is False, f"expected ALLOW: {cmd}"


def test_outside_source_still_allowed_with_resolution(fake_home):
    tmp, home, env = fake_home
    assert _run(f"cat {tmp}/outside.py", REPO, env) is False


def test_missing_realpath_degrades_to_literal_not_open(tmp_path):
    """A host without realpath keeps the old literal behaviour — never looser."""
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "realpath").write_text("#!/bin/sh\nexit 1\n")
    (shim / "realpath").chmod(0o755)
    env = {**ENV, "PATH": f"{shim}:{os.environ['PATH']}"}
    assert _run(f"cat {REPO}/scripts/referee.py", REPO, env) is True
    assert _run("grep -rn foo scripts/", REPO, env) is True
    assert _run("crontab -l | grep x", REPO, env) is False

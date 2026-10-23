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


# --- glob operands (2026-10-22) ---------------------------------------------------
# The guard sees the RAW command, so `docs/*.md` arrived as a literal path that
# isn't a file: recursive grep denied it (and every relative operand, README.md
# included), while a non-recursive `cat scripts/*` slipped through because the
# literal token has no source extension. Globs now expand against the session cwd
# and each match is judged; a plain non-source file under -r is read alone.

@pytest.fixture
def glob_repo(tmp_path):
    """A throwaway git repo: docs/*.md, scripts/*.py, a README, and bypass bait."""
    r = tmp_path / "repo"
    (r / "docs").mkdir(parents=True)
    (r / "scripts").mkdir()
    (r / "docs" / "a.md").write_text("x")
    (r / "docs" / "b.md").write_text("x")
    (r / "scripts" / "tool.py").write_text("x")
    (r / "README.md").write_text("x")
    (r / "notes").mkdir()
    (r / "notes" / "sneaky.md").symlink_to(r / "scripts" / "tool.py")   # .md -> .py
    (r / "dir.md").mkdir()                                              # a dir named *.md
    (r / "dir.md" / "inner.py").write_text("x")
    (r / "many").mkdir()
    for i in range(205):
        (r / "many" / f"f{i}.txt").write_text("x")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    return r


GLOB_ALLOW = [
    "grep -rn foo docs/*.md README.md",      # the original false positive
    "grep -rn foo README.md",                # -r on a plain non-source file
    "grep -n foo docs/*.md",
    "cat docs/*",
]
GLOB_DENY = [
    "grep -rn foo scripts/*.py",             # glob of source
    "cat scripts/*",                         # glob hiding source (was allowed)
    "grep -rn foo docs/*.md scripts/",       # mixed: a dir still walks the tree
    "grep -n foo notes/*.md",                # .md symlink resolving to repo .py
    "grep -rn foo *.md",                     # matches dir.md/, a directory under -r
    "grep -rn foo many/*",                   # over the 200-match cap: fail closed
    "grep -rn foo scripts/tool.py",          # a source file named directly under -r
    "grep -rn foo .",                        # the cwd itself
    "grep -rn foo nomatch/*.md",             # no match: the literal rule, never looser
]


@pytest.mark.parametrize("cmd", GLOB_ALLOW)
def test_glob_operands_allowed(glob_repo, cmd):
    assert _run(cmd, glob_repo) is False


@pytest.mark.parametrize("cmd", GLOB_DENY)
def test_glob_operands_denied(glob_repo, cmd):
    assert _run(cmd, glob_repo) is True


# --- 2026-10-23: the bash-aware analyzer ------------------------------------------
# The legacy scan split the raw command on spaces with no notion of quoting or of
# where the shell is. A quote-aware lexer now feeds the judging helpers; cd/pushd,
# subshells and literal VAR=value assignments are followed; wrappers, sh -c, eval
# and heredoc-fed shells are unwrapped. Every bypass below was ALLOWED before
# (or allowed only by luck) and every allow below was a real false positive.

def _run_dbg(cmd, cwd=REPO, env=None):
    payload = {"tool_input": {"command": cmd}, "session_id": "test", "cwd": str(cwd)}
    r = subprocess.run(["bash", HOOK], input=json.dumps(payload), capture_output=True,
                       text=True, env={**(env or ENV), "GREP_GUARD_DEBUG": "1"})
    return '"deny"' in r.stdout.replace(" ", ""), r.stderr


ANALYZER_DENY = [
    # cd tracking: relative paths resolve against the directory the shell is in
    "cd scripts && cat referee.py",
    "cd scripts; cat referee.py",
    "cd scripts && sed -n 1,5p referee.py",
    "pushd scripts && cat referee.py",
    "pushd scripts >/dev/null; head referee.py",
    "(cd /tmp) && cat scripts/referee.py",          # a subshell's cd does not leak out
    "cd /tmp | cat scripts/referee.py",             # nor does a pipeline stage's
    "cd /nonexistent-gg-dir; cat scripts/referee.py",  # failed cd: still in the repo
    "cd /tmp || cat scripts/referee.py",
    "cd /tmp && cd - && cat scripts/referee.py",    # OLDPWD unknown → fail closed
    "cd $GG_UNSET_DIR && cat referee.py",
    "CDPATH=/tmp cd scripts && cat referee.py",
    "f() { cd /tmp; }; f && cat scripts/referee.py",
    # quoting / escaping
    'cat "scripts/referee.py"',
    "cat scr'ipts'/referee.py",
    "c\\at scripts/referee.py",
    '"cat" scripts/referee.py',
    "cat scripts/referee.py # <<",                  # `<<` no longer exempts the command
    "cat scripts/referee.py; : <<X\nX",
    'cat "scripts/referee.py',                      # unbalanced quote: fail closed
    # command words computed at run time
    "$(echo cat) scripts/referee.py",
    "`echo cat` scripts/referee.py",
    "X=cat; $X scripts/referee.py",
    # substitutions run
    'echo "$(cat scripts/referee.py)"',
    "echo $(cat scripts/referee.py)",
    "x=$(head -5 scripts/referee.py)",
    "diff <(cat scripts/referee.py) /dev/null",
    "(cat scripts/referee.py)",
    "{ cat scripts/referee.py; }",
    "if cat scripts/referee.py >/dev/null; then echo y; fi",
    # wrappers
    "sudo cat scripts/referee.py",
    "env cat scripts/referee.py",
    "env -i PATH=/usr/bin cat scripts/referee.py",
    "timeout 5 cat scripts/referee.py",
    "nice -n 5 head scripts/referee.py",
    "command cat scripts/referee.py",
    "x=1 cat scripts/referee.py",
    "nohup tail scripts/referee.py",
    # code handed to another shell
    "bash -c 'cat scripts/referee.py'",
    'sh -c "cd scripts && cat referee.py"',
    "eval cat scripts/referee.py",
    'eval "cat scripts/referee.py"',
    "bash <<'EOF'\ncat scripts/referee.py\nEOF",
    "echo 'cat scripts/referee.py' | bash",
    # input redirection reads the file
    "cat < scripts/referee.py",
    "while read l; do echo \"$l\"; done < scripts/referee.py",
    # option syntax
    "grep -efoo scripts/referee.py",                # pattern by -e: the .py is the FILE
    "grep -e foo scripts/referee.py",
    "grep --regexp=foo scripts/referee.py",
    "grep -f scripts/referee.py README.md",         # -f reads the pattern file
    "grep -d recurse foo .",
    "grep --directories=recurse foo scripts",
    "grep -n --include '*.py' -r foo .",
    "ls | rg foo scripts/",                          # piped rg with explicit paths
    # variables
    "F=scripts/referee.py; cat $F",
    "D=scripts; cat $D/referee.py",
    'D=scripts; cat "${D}/referee.py"',
    "cat $GG_UNSET/referee.py",                      # unknown + source ext
    "for f in scripts/*.py; do cat $f; done",
    "git ls-files | while read f; do cat \"$f\"; done",
    # file lists from elsewhere
    "git ls-files | xargs grep foo",
    "find scripts -name '*.py' -exec cat {} \\;",
    "f() { cat \"$@\"; }; f scripts/referee.py",
]


@pytest.mark.parametrize("cmd", ANALYZER_DENY)
def test_analyzer_denies_bypass(cmd):
    denied, err = _run_dbg(cmd)
    assert denied is True, f"expected DENY: {cmd!r} ({err.strip()})"


ANALYZER_ALLOW = [
    # (a) quoted pattern holding a source name — the reported false positive
    "grep -e 'uv run example.py' README.md",
    "grep -n 'scripts/x.py' README.md",
    'grep -c "import x.py" CHANGELOG.md',
    "printf '%s' x | grep -c 'scripts/x.py'",
    # (b) cd away from the repo first
    "cd /tmp && cat x.py",
    "cd /tmp && grep -rn foo .",
    "cd /opt/proj/hearth && grep -rn foo src/",
    "(cd /tmp && cat x.py)",
    "pushd /tmp && head x.py",
    # literal variables (coordinator-reported false positive, 2026-10-23)
    "S=/tmp/claude-1000/-opt-proj-x/abc/scratchpad/photo; cd /opt/proj/partikus && "
    "(echo \"import sys\"; cat $S/flange_script.py) > $S/run_flange.py && python3 $S/run_flange.py",
    'S=/tmp/gg-scratch; cat "$S/a.py"',
    "S=/tmp/gg-scratch; cat ${S}/a.py",
    "export S=/tmp/gg-scratch; head $S/a.py",
    "cat $HOME/.local/bin/x.sh",
    # text that is not executed
    'echo "cat scripts/referee.py"',
    "git commit -m 'cat scripts/referee.py'",
    "cat >> CHANGELOG.md <<'EOF'\ncat scripts/referee.py\nEOF",
    "git commit -F - <<'EOF'\nfix: cat scripts/referee.py\nEOF",
    # plain reads that were always fine
    "pytest tests/test_x.py | tail -5",
    "python3 scripts/referee.py --help | head -20",
    "sed -i 's/a/b/' scripts/referee.py",
    "sed -ni 's/a/b/p' scripts/referee.py",
    "tail -n 20 state/hook-blocks.log",
    "for f in docs/a.md docs/b.md; do cat $f; done",
    "command -v cat",
]


@pytest.mark.parametrize("cmd", ANALYZER_ALLOW)
def test_analyzer_allows(cmd):
    denied, err = _run_dbg(cmd)
    assert denied is False, f"expected ALLOW: {cmd!r} ({err.strip()})"


@pytest.mark.parametrize("cmd", ["cat scripts/referee.py", "grep -e 'x.py' README.md",
                                 "cd /tmp && cat x.py"])
def test_analyzer_is_the_deciding_path(cmd):
    # A crash in the analyzer would fall back to the legacy scan and still pass most
    # cases. Pin that normal commands are decided by the analyzer.
    _, err = _run_dbg(cmd)
    assert "path=analyzer" in err, err


def test_no_python3_falls_back_to_legacy_and_still_denies(tmp_path):
    import shutil
    shim = tmp_path / "bin"
    shim.mkdir()
    for tool in ("jq", "grep", "sed", "realpath", "git", "date", "tr", "head", "iconv",
                 "wc", "find", "mkdir", "rmdir", "mv", "cat", "bash", "dirname"):
        p = shutil.which(tool)
        if p:
            os.symlink(p, shim / tool)
    env = {**ENV, "PATH": str(shim)}
    denied, err = _run_dbg("cat scripts/referee.py", env=env)
    assert denied is True and "path=legacy" in err, err
    denied, err = _run_dbg("crontab -l | grep x", env=env)
    assert denied is False, err

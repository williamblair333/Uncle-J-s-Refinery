"""Behaviour matrix for hooks/pre-mortem-guard/surface-write-guard.sh.

A security control. The BLOCK cases matter more than the ALLOW ones: this guard
was versioned in order to fix a logging defect, and a transcription slip that
narrowed detection would trade a cosmetic bug for a real false negative.

So the bulk of this file asserts that every detection pattern still denies, and
one case asserts the regex block is byte-identical to the live installed copy
when that copy is a real file rather than a symlink into the repo.

The logging cases pin the actual defect: a multi-line command must produce
exactly ONE physical log line carrying `session=`. Before the fix, `head -c`
truncated bytes rather than lines, so a heredoc spilled across four lines and
stranded `session=` on the last one — which is why a real block on 2026-08-15
was reported as "fired but logged nothing".

pytest + jq. No API calls.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "hooks" / "pre-mortem-guard" / "surface-write-guard.sh"
LIVE_GUARD = Path.home() / ".claude" / "hooks" / "pre-mortem-guard" / "surface-write-guard.sh"

DENY = "deny"


def run_guard(command: str, tmp_path: Path, session_id: str = "sess-0001",
              env_extra: dict | None = None) -> subprocess.CompletedProcess:
    payload = {"tool_input": {"command": command}, "session_id": session_id}
    env = {**os.environ, "SURFACE_GUARD_LOG": str(tmp_path / "hook-blocks.log")}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def blocked(res: subprocess.CompletedProcess) -> bool:
    if not res.stdout.strip():
        return False
    try:
        out = json.loads(res.stdout)
    except ValueError:
        return False
    return out.get("hookSpecificOutput", {}).get("permissionDecision") == DENY


def read_log(tmp_path: Path) -> list[str]:
    p = tmp_path / "hook-blocks.log"
    if not p.exists():
        return []
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ── BLOCK matrix: one case per detection pattern ─────────────────────────────
# These are the cases whose regression would be a false negative.

BLOCK_CASES = [
    ("redirect-to-sh",        "echo 'x' > /opt/proj/foo/scripts/deploy.sh"),
    ("redirect-quoted",       "echo 'x' > \"my script.sh\""),
    ("redirect-to-hooks-dir", "cat payload > /home/u/.claude/hooks/thing.txt"),
    ("redirect-midcommand",   "echo x > setup.sh && echo done"),
    ("sed-inplace-empty-suffix", 'sed -i "" build.sh'),
    ("python-open-write",     "python3 -c \"open('guard.sh','w').write('x')\""),
    ("python-open-append",    "python3 -c \"open('guard.py','a').write('x')\""),
    ("ruby-surface",          "ruby -e 'File.write(\"setup.sh\", \"x\")'"),
    ("node-surface",          "node -e 'fs.writeFileSync(\"build.sh\",\"x\")'"),
    ("awk-redirect",          "awk '{print}' in.txt > out.sh"),
    ("cp-to-surface",         "cp /tmp/evil.sh /opt/proj/x/scripts/good.sh"),
    ("mv-to-surface",         "mv /tmp/evil /opt/proj/x/hooks/guard.sh"),
]


@pytest.mark.parametrize("name,cmd", BLOCK_CASES, ids=[c[0] for c in BLOCK_CASES])
def test_surface_writes_are_blocked(name, cmd, tmp_path):
    res = run_guard(cmd, tmp_path)
    assert blocked(res), f"{name}: NOT blocked — false negative.\ncmd={cmd}\nstdout={res.stdout}"


# ── Former KNOWN GAPS, closed 2026-10-22 ─────────────────────────────────────
# Pinned as strict xfails from 2026-08-15 until fixed. Two root causes:
#   * REDIR_RE's SURF_EXT and SURF_FILE branches (and PERL/RUBY/NODE_RE's) ended in
#     a REQUIRED trailing delimiter, so a target at end-of-command was missed.
#     End of line now counts (SURF_END).
#   * SED_RE allowed only [[:space:]a-zA-Z0-9='"] between the flag and the file, so
#     it fired on nothing but macOS `sed -i "" f.sh`. It is now matched per command
#     segment: an in-place flag anywhere plus a surface target in the same segment.

CLOSED_GAPS = [
    ("append-to-sh-eol",       "echo 'x' >> setup.sh"),
    ("redirect-settings-eol",  "echo '{}' > settings.json"),
    ("redirect-claude-md-eol", "echo hi > CLAUDE.md"),
    ("sed-gnu-slashes",        "sed -i 's/a/b/' install.sh"),
    ("sed-suffix-dot",         "sed -i.bak 'sXaXbX' config.yml"),
    ("sed-dash-e",             "sed -i -e foo build.sh"),
    ("perl-inplace-slashes",   "perl -pi -e 's/a/b/' deploy.sh"),
]

# Adversarial variants tried while closing them (2026-10-22). Each was allowed by
# the guard before this change.
ADVERSARIAL_BLOCK = [
    ("subshell-paren",         "(echo x > a.sh)"),
    ("no-space-redirect-eol",  "echo x >a.sh"),
    ("noclobber-override",     "echo x >| a.sh"),
    ("amp-redirect",           "echo x &>a.sh"),
    ("redirect-ampersand-word", "echo x >& a.sh"),
    ("exec-redirect",          "exec > a.sh"),
    ("backtick-dir",           "echo x > `pwd`/a.sh"),
    ("redirect-continuation",  "echo x > \\\n f.sh"),
    ("sed-flag-after-script",  "sed -e 's/a/b/' -i build.sh"),
    ("sed-flag-last",          "sed 's/a/b/' build.sh -i"),
    ("sed-long-in-place",      "sed --in-place 's/a/b/' x.py"),
    ("sed-long-in-place-suf",  "sed --in-place=.orig 's/a/b/' x.py"),
    ("sed-combined-Ei",        "sed -Ei 's/a/b/' x.toml"),
    ("sed-combined-ni",        "sed -ni 's/a/b/p' x.cfg"),
    ("sed-separate-s-i",       "sed -s -i 's/a/b/' f.sh"),
    ("sed-empty-suffix-glued", "sed -i'' 's/a/b/' f.sh"),
    ("sed-pipe-delimiter",     "sed -i 's|a|b|' f.sh"),
    ("sed-semicolon-in-script", "sed -i 's/a;b/c/' f.sh"),
    ("sed-amp-in-script",      'sed -i "s/a&b/c/" f.sh'),
    ("sed-redirect-amp-between", "sed -i 2>&1 's/a/b/' f.sh"),
    ("sed-quoted-target",      "sed -i 's/a/b/' \"my file.sh\""),
    ("sed-claude-md",          "sed -i 's/a/b/' CLAUDE.md"),
    ("sed-settings-json",      "sed -i 's/a/b/' ~/.claude/settings.json"),
    ("sed-hooks-dir-any-ext",  "sed -i 's/a/b/' /opt/proj/x/hooks/foo.txt"),
    ("sed-abs-path",           "/bin/sed -i 's/a/b/' f.sh"),
    ("gsed",                   "gsed -i 's/a/b/' f.sh"),
    ("sed-quoted-name",        "\"sed\" -i 's/a/b/' f.sh"),
    ("sudo-sed",               "sudo sed -i 's/a/b/' f.sh"),
    ("sed-glob",               "sed -i 's/a/b/' *.sh"),
    ("find-exec-sed",          "find . -name '*.sh' -exec sed -i 's/a/b/' {} +"),
    ("find-xargs-sed",         "find . -name '*.sh' | xargs sed -i 's/a/b/'"),
    ("sed-continuation",       "sed -i \\\n 's/a/b/' f.sh"),
    ("ruby-inplace-eol",       "ruby -pi -e 'x' deploy.sh"),
    # cp/mv word boundary must still see real copies
    ("cp-after-semicolon",     "true;cp a b c.sh"),
    ("cp-in-subst",            "x=$(cp a b c.sh)"),
    ("cp-in-backticks",        "echo `cp a b c.sh`"),
    ("cp-abs-path",            "/bin/cp a b/c.sh d/e.sh"),
    ("cp-to-scripts-sh",       "cp x scripts/y.sh"),
    ("mv-to-scripts-sh",       "mv x scripts/y.sh"),
    ("cp-then-and",            "cp x y.sh && echo"),
]


@pytest.mark.parametrize("name,cmd", CLOSED_GAPS + ADVERSARIAL_BLOCK,
                         ids=[c[0] for c in CLOSED_GAPS + ADVERSARIAL_BLOCK])
def test_closed_gaps_and_adversarial_variants_blocked(name, cmd, tmp_path):
    res = run_guard(cmd, tmp_path)
    assert blocked(res), f"{name}: NOT blocked — false negative.\ncmd={cmd!r}"


# The widening must not block ordinary work: `cp` inside `mcp`, sed that doesn't
# edit in place or doesn't touch a surface file, near-miss filenames.
WIDENING_ALLOW = [
    ("claude-mcp-add",         "claude mcp add foo -- python scripts/server.py"),
    ("claude-mcp-add-abs",     "claude mcp add partikus -- uv run /opt/proj/partikus/scripts/mcp_server.py"),
    ("partikus-mcp",           "partikus_mcp tests/x.py"),
    ("python-m-partikus-mcp",  "python -m partikus_mcp -v tests/x.py"),
    ("uv-run-partikus-mcp",    "uv run partikus_mcp --check tests/x.py tests/y.py"),
    ("sed-print-only",         "sed -n 's/a/b/p' build.sh"),
    ("sed-stdout-to-txt",      "sed 's/a/b/' build.sh > out.txt"),
    ("sed-inplace-txt",        "sed -i 's/a/b/' notes.txt"),
    ("sed-inplace-txt-then-py", "sed -i 's/a/b/' notes.txt && cat x.py"),
    ("sed-inplace-md-then-py", "sed -i 's/a/b/' README.md; python3 tests/foo.py"),
    ("sed-slash-i-in-pattern", "sed -n '/-i/p' f.sh"),
    ("redirect-sh-dot-txt",    "echo hi > notes.sh.txt"),
    ("redirect-claude-md-bak", "echo hi > CLAUDE.md.bak"),
    ("redirect-shell-ext",     "echo hi > a.shell"),
    ("stderr-to-stdout-pipe",  "uv run pytest tests/test_x.py -q 2>&1 | tail -5"),
    ("ls-glob",                "ls scripts/*.sh"),
]


@pytest.mark.parametrize("name,cmd", WIDENING_ALLOW, ids=[c[0] for c in WIDENING_ALLOW])
def test_widening_does_not_block_ordinary_work(name, cmd, tmp_path):
    res = run_guard(cmd, tmp_path)
    assert not blocked(res), f"{name}: false positive.\ncmd={cmd!r}"


# ── ALLOW matrix: the guard must not block ordinary work ─────────────────────

ALLOW_CASES = [
    ("read-only-cat",     "cat /opt/proj/x/scripts/deploy.sh"),
    ("git-status",        "git status --short"),
    ("redirect-to-txt",   "echo hi > /tmp/notes.txt"),
    ("redirect-to-md",    "echo hi > README.md"),
    ("pipe-to-grep",      "cat foo.log | grep error"),
    ("ls",                "ls -la /opt/proj"),
]


# ── Scratch writes under /tmp are not surface writes (2026-10-16) ────────────────
#    The guard blocked `cat > $scratchpad/probe.py` and backups copied INTO scratch.
#    A /tmp target is exempt only when it RESOLVES under /tmp: `..`, symlinks, `ln`
#    in the same command, reassigned variables and the pre-mortem token path are not.

SCRATCH_ALLOW = [
    ("heredoc-scratch-py",  "cat > /tmp/claude-1000/s/scratchpad/probe.py <<'EOF'\nprint(1)\nEOF"),
    ("redirect-scratch-sh", "echo x > /tmp/probe.sh && echo done"),
    ("cp-backup-to-scratch", "cp /opt/proj/hearth/house/house.yaml /tmp/claude-1000/s/house.yaml.bak"),
    ("scratch-var-heredoc", "S=/tmp/claude-1000/s/scratchpad; cat > $S/rehearsal.yaml <<'EOF'\na: 1\nEOF"),
    ("scratch-var-braced",  'S=/tmp/claude-1000/s; echo x > "${S}/run.sh" && bash ${S}/run.sh'),
]


@pytest.mark.parametrize("name,cmd", SCRATCH_ALLOW, ids=[c[0] for c in SCRATCH_ALLOW])
def test_scratch_writes_under_tmp_allowed(name, cmd, tmp_path):
    res = run_guard(cmd, tmp_path)
    assert not blocked(res), f"{name}: false positive on a /tmp scratch write.\ncmd={cmd}"


SCRATCH_ESCAPE_BLOCK = [
    ("dotdot-escape",       "echo x > /tmp/../opt/proj/x/scripts/a.sh"),
    ("ln-same-command",     "ln -s /opt/proj/x/hooks /tmp/l && echo x > /tmp/l/a.sh && echo done"),
    ("var-reassigned",      "S=/tmp/x; S=/opt/proj/x/scripts; echo y > $S/a.sh && echo done"),
    ("var-appended",        "S=/tmp/x; S+=/../../opt/proj/x; echo y > $S/a.sh && echo done"),
    ("var-from-loop",       "for S in /opt/proj/x/hooks; do S=/tmp/x; done; echo y > $S/a.sh && echo done"),
    ("cp-from-tmp-to-surface", "cp /tmp/evil.sh /opt/proj/x/scripts/good.sh"),
    # a /tmp token glued to shell syntax must not take the next command with it
    ("glued-separator",     "echo x >/tmp/a;cp /tmp/e hooks/g.sh"),
    ("token-path",          "cp payload.sh /tmp/premortem-cleared-sess.sh && echo done"),
    ("quote-split-var",     'S="/tmp/x /opt/proj/x/hooks"; cp a.txt $S/a.sh && echo done'),
    # security review 2026-10-16: removal must be per-operand, not a global substring
    ("substring-in-hooks",  ": /tmp/foo ; echo hi > /opt/proj/R/hooks/tmp/foo ;"),
    ("substring-in-ext",    ": /tmp/foo.sh ; echo hi > /opt/proj/R/tmp/foo.sh ;"),
    # a prefix assignment binds only for that command, not the redirect's expansion
    ("prefix-assignment",   "d=/tmp/x cat > $d/a.sh ;"),
    # rebinding without a literal `d=`
    ("printf-v-rebind",     "d=/tmp/x; printf -v d %s /opt/proj/R/hooks; echo x > $d/a.sh ;"),
    ("eval-rebind",         'd=/tmp/x; eval "d""=/opt/proj/R/hooks"; echo x > $d/a.sh ;'),
    # mv into /tmp deletes the surface source (found replaying hook-blocks.log)
    ("mv-surface-into-tmp", "mv analyzer/chesslab/lines.py /tmp/lines.py.bak && echo moved"),
    # heredoc bodies that get EXECUTED stay scanned (body skip is cat-to-file only)
    ("heredoc-piped-to-bash", "cat <<'EOF' | bash\necho x > /opt/proj/x/hooks/a.sh\nEOF"),
    ("heredoc-cmd-subst",     "bash -c \"$(cat <<'EOF'\necho x > /opt/proj/x/hooks/a.sh\nEOF\n)\""),
    ("heredoc-into-bash",     "bash <<'EOF'\necho x > /opt/proj/x/hooks/a.sh\nEOF"),
    ("heredoc-to-surface",    "cat > /opt/proj/x/hooks/a.sh <<'EOF'\nhi\nEOF"),
    ("after-heredoc-end",     "cat > /tmp/n.md <<'EOF'\nhi\nEOF\necho x > /opt/proj/x/hooks/a.sh"),
    # a quoted or escaped `<<` is an argument, not a heredoc: the next lines are commands
    ("quoted-lt-lt",          "cat \"<<X\"\necho x > /opt/proj/x/hooks/a.sh"),
    ("escaped-lt-lt",         "cat \\<<X\necho x > /opt/proj/x/hooks/a.sh"),
    # the body becomes code if anything in the same command can execute it
    ("heredoc-then-run",      "cat > /tmp/x.sh <<'EOF'\necho x > /opt/proj/x/hooks/a.sh\nEOF\nbash /tmp/x.sh"),
    ("heredoc-procsub-bash",  "cat <<'EOF' > >(bash)\necho x > /opt/proj/x/hooks/a.sh\nEOF"),
    ("heredoc-exec-fd",       "exec 3> >(sh)\ncat <<'EOF' >&3\necho x > /opt/proj/x/hooks/a.sh\nEOF"),
    ("heredoc-then-dot-slash", "cat > x.txt <<'EOF'\necho x > /opt/proj/x/hooks/a.sh\nEOF\nchmod +x x.txt; ./x.txt"),
    # security review 2026-10-16 (round 2): the parser must end the body where bash does
    ("pieced-delimiter-dq",   'cat <<E"OF"\nx\nEOF\necho hi > /opt/proj/x/hooks/evil.sh\nE'),
    ("pieced-delimiter-sq",   "cat <<E'O'F\nx\nEOF\necho hi > /opt/proj/x/hooks/evil.sh\nE"),
    ("continuation-target",   "cat <<EOF \\\n> /opt/proj/x/hooks/evil.sh\nbody\nEOF"),
    ("continuation-and",      "cat <<EOF && \\\necho hi > /opt/proj/x/hooks/evil.sh\nbody\nEOF"),
    ("crlf-delimiter",        "cat <<EOF\r\nbody\r\nEOF\r\necho hi > /opt/proj/x/hooks/evil.sh\r\n"),
    ("group-cat-bash",        "{ cat; bash; } <<EOF\necho x > /opt/proj/x/hooks/a.sh\nEOF"),
    ("no-space-then-write",   "cat<<EOF\nx\nEOF\necho y > /opt/proj/x/hooks/a.sh"),
    ("sh-dash-s",             "sh -s <<EOF\necho x > /opt/proj/x/hooks/a.sh\nEOF"),
]


# ── A cat heredoc's BODY is data, not commands (2026-10-16) ──────────────────────
#    Notes and audit records that merely mention a redirect-shaped path were blocked.

HEREDOC_BODY_ALLOW = [
    ("audit-note",  "cat >> ~/.uncle-j-memory/memory/audit-baselines.md <<'PM_EOF'\n"
                    "- closed: `echo > /opt/proj/R/hooks/tmp/foo` erased the marker\nPM_EOF"),
    ("dash-heredoc", "cat > /tmp/s/notes.txt <<-EOF\n\tcp a.sh /opt/proj/x/scripts/b.sh\n\tEOF"),
    # <<- strips TABS only: "  EOF" never closes it, so bash reads every later line as
    # body (data for cat), exactly as the parser does
    ("dash-heredoc-spaces-unclosed", "cat <<-EOF\n  x\n  EOF\necho hi > /opt/proj/x/hooks/b.sh && echo"),
]


@pytest.mark.parametrize("name,cmd", HEREDOC_BODY_ALLOW, ids=[c[0] for c in HEREDOC_BODY_ALLOW])
def test_cat_heredoc_body_is_not_scanned(name, cmd, tmp_path):
    res = run_guard(cmd, tmp_path)
    assert not blocked(res), f"{name}: heredoc body text was scanned as a command.\ncmd={cmd}"


@pytest.mark.parametrize("name,cmd", SCRATCH_ESCAPE_BLOCK, ids=[c[0] for c in SCRATCH_ESCAPE_BLOCK])
def test_tmp_exemption_cannot_be_escaped(name, cmd, tmp_path):
    res = run_guard(cmd, tmp_path)
    assert blocked(res), f"{name}: /tmp exemption escaped — false negative.\ncmd={cmd}"


def test_existing_symlink_out_of_tmp_still_blocked(tmp_path):
    # tmp_path lives under /tmp; a link inside it pointing at a hooks dir resolves out.
    assert str(tmp_path.resolve()).startswith("/tmp/")
    link = tmp_path / "l"
    link.symlink_to(REPO_ROOT / "hooks")
    res = run_guard(f"echo x > {link}/a.sh && echo done", tmp_path)
    assert blocked(res), "symlink out of /tmp was treated as scratch"


@pytest.mark.parametrize("name,cmd", ALLOW_CASES, ids=[c[0] for c in ALLOW_CASES])
def test_ordinary_commands_are_allowed(name, cmd, tmp_path):
    res = run_guard(cmd, tmp_path)
    assert not blocked(res), f"{name}: false positive — blocked an ordinary command.\ncmd={cmd}"
    assert res.returncode == 0


# ── the logging defect this file exists to fix ───────────────────────────────

def test_multiline_command_writes_exactly_one_log_line(tmp_path):
    """The defect: `head -c` cuts bytes, not lines.

    A heredoc previously wrote four physical lines with `session=` stranded on
    the last, so searching for a BLOCKED line carrying the session id found
    nothing and the block was reported as unlogged.
    """
    cmd = (
        "mkdir -p ~/.uncle-j-memory/memory\n"
        "cat >> ~/.uncle-j-memory/memory/audit-baselines.md <<'EOF'\n"
        "\n"
        "## [AUDIT BASELINE] some heading\n"
        "EOF\n"
        "echo done > /opt/proj/x/scripts/after.sh"
    )
    res = run_guard(cmd, tmp_path, session_id="7fff9c86-ca82-4f0e-9049-17c3ab60b2bf")
    assert blocked(res)

    lines = read_log(tmp_path)
    assert len(lines) == 1, f"expected 1 log line, got {len(lines)}: {lines}"
    assert "session=7fff9c86-ca82-4f0e-9049-17c3ab60b2bf" in lines[0]
    assert lines[0].startswith("20"), "log line must start with a timestamp"
    assert "\n" not in lines[0]


def test_log_line_is_greppable_by_session(tmp_path):
    """The weekly review searches for BLOCKED + session= on one line."""
    run_guard("printf 'a\\nb' > /opt/proj/x/scripts/x.sh", tmp_path, session_id="abc-123")
    lines = read_log(tmp_path)
    assert len(lines) == 1
    assert re.search(r"BLOCKED surface-write-guard .*session=abc-123", lines[0])


def test_tabs_and_carriage_returns_collapsed(tmp_path):
    cmd = "echo\t'x'\r\n> /opt/proj/x/scripts/tabbed.sh"
    run_guard(cmd, tmp_path)
    lines = read_log(tmp_path)
    assert len(lines) == 1
    assert "\t" not in lines[0]
    assert "\r" not in lines[0]


def test_allowed_command_writes_no_log_line(tmp_path):
    run_guard("git status", tmp_path)
    assert read_log(tmp_path) == []


# ── fail-loud on missing jq (was: silently allow everything) ─────────────────

def test_missing_jq_fails_loudly_instead_of_allowing(tmp_path):
    """Without jq the old guard parsed an empty CMD and exit 0'd — silently
    allowing every command it exists to screen."""
    fake_bin = tmp_path / "emptybin"
    fake_bin.mkdir()
    for tool in ("bash", "grep", "date", "printf", "tr", "head", "cat", "echo", "sed"):
        real = shutil.which(tool)
        if real:
            (fake_bin / tool).symlink_to(real)

    res = subprocess.run(
        ["bash", str(GUARD)],
        input=json.dumps({"tool_input": {"command": "echo x > evil.sh"}, "session_id": "s"}),
        capture_output=True,
        text=True,
        env={"PATH": str(fake_bin), "HOME": str(tmp_path)},
        timeout=30,
    )
    assert res.returncode != 0, "guard must not exit 0 when jq is unavailable"
    assert "jq not found" in res.stderr


def test_empty_command_is_allowed(tmp_path):
    res = run_guard("", tmp_path)
    assert res.returncode == 0
    assert not blocked(res)


# ── the ported regexes must not have drifted ─────────────────────────────────

REGEX_VARS = ["SURF_EXT", "SURF_PATH", "SURF_FILE", "REDIR_RE", "SED_RE",
              "PY_RE", "PERL_RE", "RUBY_RE", "NODE_RE", "AWK_RE", "CP_RE"]


def _extract_regex_lines(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        for var in REGEX_VARS:
            if line.startswith(f"{var}="):
                out[var] = line
    return out


def test_all_regex_definitions_present():
    defs = _extract_regex_lines(GUARD)
    missing = [v for v in REGEX_VARS if v not in defs]
    assert not missing, f"detection regexes missing from the versioned guard: {missing}"


@pytest.mark.skipif(not LIVE_GUARD.exists(), reason="live guard not installed on this machine")
@pytest.mark.skipif(LIVE_GUARD.is_symlink(),
                    reason="live guard is a symlink into a checkout of this file: comparing "
                           "it compares two branches, and every detection change differs by design")
def test_regexes_byte_identical_to_live_guard():
    """A live guard that is a REAL FILE must detect what the versioned one does.

    This guarded the 2026-08-15 move from an unversioned live copy into the repo.
    Since the installer symlinks the live path to the repo, it only still fires on a
    machine where a stale real-file copy shadows the repo version.
    """
    repo_defs = _extract_regex_lines(GUARD)
    live_defs = _extract_regex_lines(LIVE_GUARD)
    for var in REGEX_VARS:
        assert repo_defs.get(var) == live_defs.get(var), (
            f"{var} differs from the live guard — detection may have narrowed.\n"
            f"repo: {repo_defs.get(var)!r}\nlive: {live_defs.get(var)!r}"
        )

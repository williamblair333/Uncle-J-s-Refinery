"""check_clears.py + write-clearance-token.sh: a pre-mortem whose risky CLEARs cite
nothing checked earns no token.

The regression case is the real rhcsa-lab pre-mortem from 2026-11-27, whose
"[ RECOVERY ] ✓ CLEAR: vm-destroy is the rollback; the ISO is never modified"
preceded the deletion of the ISO.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECK = REPO / "hooks" / "pre-mortem-guard" / "check_clears.py"
WRITER = REPO / "hooks" / "pre-mortem-guard" / "write-clearance-token.sh"
FIX = REPO / "tests" / "fixtures" / "premortem"
INCIDENT = FIX / "rhcsa-2026-11-27-iso-deleted.txt"
GOOD = FIX / "delete-guard-2026-11-27.txt"
BASH = shutil.which("bash") or "/bin/bash"


def check(path: Path):
    return subprocess.run(["python3", "-I", str(CHECK), str(path)], capture_output=True, text=True)


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "pm.txt"
    p.write_text(text)
    return p


def test_incident_premortem_is_refused():
    r = check(INCIDENT)
    assert r.returncode == 1
    assert "[ RECOVERY ]" in r.stderr and "ISO is never modified" in r.stderr
    assert "[ DATA INTEGRITY ]" in r.stderr


def test_cited_premortem_passes():
    r = check(GOOD)
    assert r.returncode == 0, r.stderr


def test_risky_clear_with_citation_passes(tmp_path):
    p = write(tmp_path, "[ RECOVERY ] ✓ CLEAR — revert the commit (checked: git log -1 shows abc123)\nSTATUS: ✓ CLEAR TO PROCEED\n")
    assert check(p).returncode == 0


def test_citation_on_a_later_line_of_the_block_counts(tmp_path):
    p = write(tmp_path, "[ SECURITY ] ✓ CLEAR — token never echoed\n  (checked: scripts/x.sh:12 reads it into a header)\nSTATUS: ok\n")
    assert check(p).returncode == 0


def test_too_short_citation_is_refused(tmp_path):
    p = write(tmp_path, "[ RECOVERY ] ✓ CLEAR — fine (checked: yes)\nSTATUS: ok\n")
    assert check(p).returncode == 1


def test_absolute_claim_on_any_dimension_needs_citation(tmp_path):
    p = write(tmp_path, "[ CONCURRENCY ] ✓ CLEAR — two runs can never overlap\nSTATUS: ok\n")
    r = check(p)
    assert r.returncode == 1 and "never" in r.stderr


def test_plain_clear_on_other_dimension_passes(tmp_path):
    p = write(tmp_path, "[ SCALE ] ✓ CLEAR — 9 commits, small.\nSTATUS: ok\n")
    assert check(p).returncode == 0


def test_findings_are_not_clears(tmp_path):
    p = write(tmp_path, "[ RECOVERY ] ⚠ MEDIUM\n  Adversarial: the rollback deletes the ISO.\nSTATUS: ⚠ WARNINGS PRESENT\n")
    assert check(p).returncode == 0


def test_colon_style_clear_is_recognised(tmp_path):
    p = write(tmp_path, "[ DATA INTEGRITY ] ✓ CLEAR: it never overwrites\nSTATUS: ok\n")
    assert check(p).returncode == 1


def test_clear_on_the_line_under_the_header_is_checked(tmp_path):
    """review 2026-11-27: only the header line was read."""
    p = write(tmp_path, "[ RECOVERY ]\n  ✓ CLEAR — rollback is fine, ISO never modified\nSTATUS: ok\n")
    assert check(p).returncode == 1


def test_severity_word_inside_a_clear_does_not_hide_it(tmp_path):
    p = write(tmp_path, "[ RECOVERY ] ✓ CLEAR — HIGH confidence the rollback is safe\nSTATUS: ok\n")
    assert check(p).returncode == 1


def test_citation_after_token_scope_does_not_count(tmp_path):
    p = write(tmp_path, "[ RECOVERY ] ✓ CLEAR — fine\nTOKEN SCOPE: x (checked: aaaaaaaaaa)\nSTATUS: ok\n")
    assert check(p).returncode == 1


def test_clear_further_down_the_block_is_checked(tmp_path):
    p = write(tmp_path, "[ RECOVERY ]\n  Adversarial: x\n  ✓ CLEAR — never\nSTATUS: ok\n")
    assert check(p).returncode == 1


def test_bracketed_token_scope_does_not_lend_its_citation(tmp_path):
    p = write(tmp_path, "[ RECOVERY ] ✓ CLEAR — fine\n[ TOKEN SCOPE ] x (checked: aaaaaaaaaa)\nSTATUS: ok\n")
    assert check(p).returncode == 1


def test_empty_or_partial_file_is_refused(tmp_path):
    assert check(write(tmp_path, "looks fine to me\n")).returncode == 1
    assert check(write(tmp_path, "[ SCALE ] ✓ CLEAR — small\n")).returncode == 1  # no STATUS line
    assert check(tmp_path / "missing.txt").returncode == 1


def run_writer(tmp_path: Path, *args: str, env=None):
    return subprocess.run([BASH, str(WRITER), *args], capture_output=True, text=True, env=env)


def test_writer_requires_the_analysis(tmp_path):
    tok = tmp_path / "premortem-cleared-x"
    r = run_writer(tmp_path, str(tok))
    assert r.returncode == 2 and "analysis-file" in r.stderr and not tok.exists()


def test_writer_refuses_incident_and_writes_nothing(tmp_path):
    tok = tmp_path / "premortem-cleared-x"
    r = run_writer(tmp_path, str(tok), str(INCIDENT))
    assert r.returncode == 1 and not tok.exists()
    assert "no token written" in r.stderr


def test_writer_writes_token_for_cited_analysis(tmp_path):
    tok = tmp_path / "premortem-cleared-x"
    r = run_writer(tmp_path, str(tok), str(GOOD))
    assert r.returncode == 0, r.stderr
    assert '"status": "PRE-MORTEM-COMPLETE"' in tok.read_text()


def test_writer_fails_closed_without_python(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("basename", "dirname", "readlink", "rm", "date", "chmod"):
        src = shutil.which(tool)
        if src:
            (bindir / tool).symlink_to(src)
    tok = tmp_path / "premortem-cleared-x"
    r = run_writer(tmp_path, str(tok), str(GOOD), env={"PATH": str(bindir)})
    assert r.returncode != 0 and not tok.exists()

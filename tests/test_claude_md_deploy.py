"""Regression tests for deploying the routing policy to ~/.claude/CLAUDE.md.

One invariant, and it had no test until content was already lost:

    Deploying the repo's CLAUDE.md MUST NOT discard the installed copy's
    "## Dreaming Notes (auto-generated)" tail.

features/dreaming/dream.sh appends that section to ~/.claude/CLAUDE.md and never to
the repo copy, so the playbooks under it exist in no other file. install.sh used to
deploy with a wholesale `cp`, which deletes them. That is not hypothetical: the
global-only "Docker Port Registry" section went the same way — scripts/audit/
components.json still lists it as a routing-policy heading, and it now appears zero
times in either file.

Both writers depend on this invariant, so it is pinned at the shared implementation
(refinery-doctor.sh's claude-md-sync fix path) plus a source-level guard on
install.sh, which CI otherwise never executes at all.

Everything runs against a temp HOME. No writes to the real ~/.claude.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCTOR = REPO_ROOT / "scripts" / "refinery-doctor.sh"
INSTALL_SH = REPO_ROOT / "install.sh"

MARKER = "## Dreaming Notes (auto-generated)"
PLAYBOOK = "- **Blocked task reporting**: lead with the outcome in bold."
DREAM_TAIL = f"{MARKER}\n\n<!-- Last updated: 2026-08-19T13:00:01Z -->\n\n{PLAYBOOK}\n"


# ── helpers ────────────────────────────────────────────────────────────────

def run_doctor(home: Path, repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run refinery-doctor against a throwaway HOME and a throwaway repo root.

    The script derives REPO_ROOT from its own location, so the repo copy under test
    is injected by running a copy of the script from inside the fake repo.
    """
    scripts = repo / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    shim = scripts / "refinery-doctor.sh"
    shim.write_bytes(DOCTOR.read_bytes())

    return subprocess.run(
        ["bash", str(shim), *args],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "HOME": str(home)},
    )


def make_env(tmp_path: Path, installed_body: str | None, repo_body: str) -> tuple[Path, Path]:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text(repo_body, encoding="utf-8")
    if installed_body is not None:
        (home / ".claude" / "CLAUDE.md").write_text(installed_body, encoding="utf-8")
    return home, repo


def installed_text(home: Path) -> str:
    return (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")


# ── the invariant ──────────────────────────────────────────────────────────

def test_fix_preserves_dreaming_notes_while_updating_policy(tmp_path):
    """The whole point. Policy prefix advances; the tail survives untouched."""
    home, repo = make_env(
        tmp_path,
        installed_body=f"# Policy\n\nOLD RULE\n\n{DREAM_TAIL}",
        repo_body="# Policy\n\nNEW RULE\n",
    )

    res = run_doctor(home, repo, "--fix", "--check", "claude-md-sync")

    out = installed_text(home)
    assert "NEW RULE" in out, f"policy prefix not updated: {res.stderr}"
    assert "OLD RULE" not in out
    assert MARKER in out, "Dreaming Notes heading was discarded"
    assert PLAYBOOK in out, "playbook content was discarded — it exists nowhere else"


def test_fix_is_idempotent_and_reports_in_sync(tmp_path):
    """A second run must not duplicate the tail or report perpetual drift."""
    home, repo = make_env(
        tmp_path,
        installed_body=f"# Policy\n\nOLD RULE\n\n{DREAM_TAIL}",
        repo_body="# Policy\n\nNEW RULE\n",
    )
    run_doctor(home, repo, "--fix", "--check", "claude-md-sync")
    first = installed_text(home)

    res = run_doctor(home, repo, "--fix", "--check", "claude-md-sync")

    assert installed_text(home) == first, "second fix changed the file again"
    assert installed_text(home).count(MARKER) == 1, "Dreaming Notes duplicated"
    assert res.returncode == 0, "an already-synced file must not report a pending migration"
    assert "in sync" in res.stderr


def test_no_dreaming_notes_still_syncs(tmp_path):
    """A machine that has never run dream.sh has no tail — plain replacement is fine."""
    home, repo = make_env(
        tmp_path,
        installed_body="# Policy\n\nOLD RULE\n",
        repo_body="# Policy\n\nNEW RULE\n",
    )
    run_doctor(home, repo, "--fix", "--check", "claude-md-sync")
    out = installed_text(home)
    assert "NEW RULE" in out and "OLD RULE" not in out
    assert MARKER not in out


def test_missing_installed_copy_is_created(tmp_path):
    """First provision: nothing to preserve, so the repo copy lands verbatim."""
    home, repo = make_env(tmp_path, installed_body=None, repo_body="# Policy\n\nNEW RULE\n")
    run_doctor(home, repo, "--fix", "--check", "claude-md-sync")
    assert "NEW RULE" in installed_text(home)


def test_fix_leaves_a_backup(tmp_path):
    """The rebuild is recoverable even if the merge logic is ever wrong."""
    home, repo = make_env(
        tmp_path,
        installed_body=f"# Policy\n\nOLD RULE\n\n{DREAM_TAIL}",
        repo_body="# Policy\n\nNEW RULE\n",
    )
    run_doctor(home, repo, "--fix", "--check", "claude-md-sync")
    backup = home / ".claude" / "CLAUDE.md.bak"
    assert backup.exists()
    assert "OLD RULE" in backup.read_text(encoding="utf-8")


def test_fix_exits_nonzero_after_applying(tmp_path):
    """Pins the trap install.sh has to guard against.

    refinery-doctor exits 1 when it applied a migration — in --fix mode that is the
    SUCCESS path. install.sh runs `set -euo pipefail`, so an unguarded call would
    abort the installer mid-run, on a working fix, and skip every later section.
    If this ever starts returning 0, install.sh's rc handling can be simplified —
    until then it must not be.
    """
    home, repo = make_env(
        tmp_path,
        installed_body="# Policy\n\nOLD RULE\n",
        repo_body="# Policy\n\nNEW RULE\n",
    )
    res = run_doctor(home, repo, "--fix", "--check", "claude-md-sync")
    assert res.returncode == 1, "doctor no longer signals 'migration applied' with exit 1"
    assert "applied" in res.stdout


# ── install.sh must not regress to a wholesale copy ────────────────────────

def test_install_sh_never_copies_over_an_existing_global_claude_md():
    """CI never executes install.sh, so guard the shape at source level.

    The lost Docker Port Registry section is what a plain `cp` costs. This asserts the
    unguarded copy is gone; the only surviving cp is the create-when-absent branch,
    where there is nothing to destroy.
    """
    src = INSTALL_SH.read_text(encoding="utf-8")
    start = src.index("# --- 6b.")
    section = src[start:src.index("# --- 6c.", start)]

    copies = [ln.strip() for ln in section.splitlines()
              if ln.strip().startswith("cp ") and "_CLAUDE_SRC" in ln]
    assert copies == ['cp "$_CLAUDE_SRC" "$_CLAUDE_DEST"'], \
        f"unexpected copy of the repo policy over the installed one: {copies}"

    # ...and that one copy must sit behind a not-present guard.
    assert '[ ! -f "$_CLAUDE_DEST" ]' in section
    assert "refinery-doctor.sh" in section, "the safe merge path is gone"


def test_install_sh_captures_the_doctor_exit_status():
    """`set -e` + doctor's exit-1-on-success is the abort trap. Pin the guard."""
    src = INSTALL_SH.read_text(encoding="utf-8")
    section = src[src.index("# --- 6b."):src.index("# --- 6c.")]
    assert "_doctor_rc=0" in section
    assert "|| _doctor_rc=$?" in section

    # Comment lines are excluded deliberately: the section *explains* why a bare
    # `|| true` is wrong, and matching that prose would fail on the documentation
    # rather than on the code.
    code = [ln for ln in section.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("|| true" in ln for ln in code), \
        "a bare `|| true` would swallow a genuine crash"


@pytest.mark.parametrize("marker_source", [
    REPO_ROOT / "features" / "dreaming" / "dream.sh",
    REPO_ROOT / "scripts" / "refinery-doctor.sh",
])
def test_marker_string_agrees_across_its_two_owners(marker_source):
    """The marker is duplicated in exactly two files and they are not linked.

    A mismatch silently restores whole-file comparison, which reports drift forever
    and makes --fix rewrite the file on every run. install.sh deliberately holds no
    third copy.
    """
    assert MARKER in marker_source.read_text(encoding="utf-8"), \
        f"{marker_source.name} no longer contains the marker {MARKER!r}"

"""Regression tests for scripts/memweave/mirror_vault.py.

The mirror copies vault notes into the memweave corpus. Two properties matter more
than the copying, and both come straight out of the pre-mortem:

  * **Pruning cannot escape its own directory.** The prune step deletes files. A
    destination resolved one level too high would take out every transcript
    document in the corpus — plus the dream-synthesis notes and the pre-mortem
    audit sink, which no re-export can regenerate.

  * **Exclusions fail closed.** The vault holds a personal-context note (health,
    key people, beliefs) and an archive carrying a plaintext credential. A
    denylist alone fails open on the next folder somebody adds, so an
    unrecognised top-level folder must be excluded *and* reported.

Everything runs against a synthetic vault in tmp_path. No memweave, no embeddings,
no network.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "memweave" / "mirror_vault.py"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "memweave"))
import mirror_vault  # noqa: E402

SECRET = "SUPERSECRET-VAULT-CREDENTIAL-abc123"


# ── helpers ────────────────────────────────────────────────────────────────

def make_vault(tmp_path: Path) -> Path:
    """A synthetic vault carrying one note per interesting category."""
    vault = tmp_path / "brain"
    files = {
        "VAULT-INDEX.md": "# Index\n\nthe map\n",
        "Active Priorities.md": "# Priorities\n\nopen work\n",
        "00 - Inbox/Inbox.md": "# Inbox\n",
        "02 - Uncle J's Refinery/Uncle J's Refinery.md": "# Refinery\n\nthe stack\n",
        "13 - Resources/Jobs/Ship a Change.md": "# Ship a Change\n\nthe job\n",
        # Excluded by policy.
        "11 - Personal/Personal Context.md": "# Personal Context\n\nhealth stuff\n",
        "11 - Personal/Personal.md": "# Personal\n",
        "12 - Archive/Migrated Memory/old.md": f"# Old\n\npassword: {SECRET}\n",
        # Never mirrored: dot dirs and non-markdown.
        ".obsidian/workspace.json": "{}\n",
        "02 - Uncle J's Refinery/diagram.png": "notreallyapng\n",
    }
    for rel, body in files.items():
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return vault


def make_workspace(tmp_path: Path) -> Path:
    """A workspace whose corpus already holds transcript docs the mirror must not touch."""
    ws = tmp_path / "store"
    mem = ws / "memory"
    mem.mkdir(parents=True)
    (mem / "session-aaaa.md").write_text("# Session aaaa\n\ntranscript\n", encoding="utf-8")
    (mem / "premortem-audit.md").write_text("# audit sink\n", encoding="utf-8")
    return ws


def mirrored(ws: Path) -> set[str]:
    dest = ws / "memory" / "vault"
    if not dest.exists():
        return set()
    return {str(p.relative_to(dest)) for p in dest.rglob("*.md")}


def corpus_roots(ws: Path) -> set[str]:
    """Transcript-level docs — everything directly in memory/, excluding the mirror."""
    return {p.name for p in (ws / "memory").glob("*.md")}


def run_script(vault: Path, ws: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--vault", str(vault), "--out", str(ws)],
        capture_output=True, text=True, timeout=60,
    )


# ── prune blast radius: the HIGH finding ───────────────────────────────────

def test_prune_never_touches_the_transcript_corpus(tmp_path):
    """The mirror owns memory/vault/ and nothing above it."""
    vault, ws = make_vault(tmp_path), make_workspace(tmp_path)
    mirror_vault.mirror(vault, ws)
    assert corpus_roots(ws) == {"session-aaaa.md", "premortem-audit.md"}


def test_empty_vault_does_not_delete_the_corpus(tmp_path):
    """Source with zero notes is the path straight into 'every dest file is an orphan'.

    VAULT_ROOT is an accepted override, so pointing it at an empty directory is a
    plausible mistake — and must not read as 'delete everything'.
    """
    ws = make_workspace(tmp_path)
    mirror_vault.mirror(make_vault(tmp_path), ws)
    assert mirrored(ws), "precondition: mirror populated"

    empty = tmp_path / "empty"
    empty.mkdir()
    r = mirror_vault.mirror(empty, ws)

    assert r["copied"] == 0
    assert mirrored(ws) == set(), "mirror should be emptied"
    assert corpus_roots(ws) == {"session-aaaa.md", "premortem-audit.md"}, "corpus survived"


def test_resolve_dest_rejects_a_dest_that_is_the_corpus_root(tmp_path, monkeypatch):
    """Neutering MIRROR_DIRNAME must raise, not silently target memory/ itself."""
    ws = make_workspace(tmp_path)
    monkeypatch.setattr(mirror_vault, "MIRROR_DIRNAME", "")
    with pytest.raises(ValueError, match="refusing to mirror"):
        mirror_vault._resolve_dest(ws)


def test_resolve_dest_rejects_escaping_the_corpus(tmp_path, monkeypatch):
    ws = make_workspace(tmp_path)
    monkeypatch.setattr(mirror_vault, "MIRROR_DIRNAME", "../../elsewhere")
    with pytest.raises(ValueError, match="refusing to mirror"):
        mirror_vault._resolve_dest(ws)


def test_dest_is_a_strict_subpath_named_vault(tmp_path):
    ws = make_workspace(tmp_path)
    dest = mirror_vault._resolve_dest(ws)
    assert dest.name == "vault"
    assert dest.parent == (ws / "memory").resolve()


# ── exclusions fail closed ─────────────────────────────────────────────────

def test_sensitive_folders_are_never_mirrored(tmp_path):
    """Personal Context (health, key people) and the credential-bearing Archive."""
    vault, ws = make_vault(tmp_path), make_workspace(tmp_path)
    mirror_vault.mirror(vault, ws)

    files = mirrored(ws)
    assert not any(f.startswith("11 - Personal") for f in files)
    assert not any(f.startswith("12 - Archive") for f in files)

    body = "\n".join(p.read_text(encoding="utf-8")
                     for p in (ws / "memory").rglob("*.md"))
    assert SECRET not in body


def test_unknown_top_level_folder_is_excluded_and_reported(tmp_path):
    """A denylist fails open on the next folder somebody adds. This one must not."""
    vault, ws = make_vault(tmp_path), make_workspace(tmp_path)
    newf = vault / "14 - Finances" / "Bank.md"
    newf.parent.mkdir(parents=True)
    newf.write_text("# Bank\n\naccount details\n", encoding="utf-8")

    r = mirror_vault.mirror(vault, ws)

    assert r["unknown_folders"] == ["14 - Finances"]
    assert not any(f.startswith("14 - Finances") for f in mirrored(ws))

    res = run_script(vault, ws)
    assert res.returncode == 1, "an unclassified folder must fail loudly"
    assert "14 - Finances" in res.stderr


def test_exclusion_survives_folder_renumbering(tmp_path):
    """Matching on the literal name would let '11 - Personal' -> '09 - Personal' leak."""
    assert mirror_vault.classify_top_level("11 - Personal") == "exclude"
    assert mirror_vault.classify_top_level("09 - Personal") == "exclude"
    assert mirror_vault.classify_top_level("3 - personal") == "exclude"
    assert mirror_vault.classify_top_level("12 - Archive") == "exclude"
    assert mirror_vault.classify_top_level("07 - Partikus") == "include"
    assert mirror_vault.classify_top_level("14 - Finances") == "unknown"


def test_dot_dirs_and_non_markdown_are_skipped(tmp_path):
    vault, ws = make_vault(tmp_path), make_workspace(tmp_path)
    mirror_vault.mirror(vault, ws)
    files = mirrored(ws)
    assert not any(".obsidian" in f for f in files)
    assert not list((ws / "memory" / "vault").rglob("*.png"))


def test_root_level_notes_are_mirrored(tmp_path):
    """VAULT-INDEX and Active Priorities are the map and the queue — the two files
    a prior-art search most wants, and they have no folder to classify."""
    vault, ws = make_vault(tmp_path), make_workspace(tmp_path)
    mirror_vault.mirror(vault, ws)
    files = mirrored(ws)
    assert "VAULT-INDEX.md" in files
    assert "Active Priorities.md" in files


# ── copying, pruning, idempotence ──────────────────────────────────────────

def test_copies_are_byte_identical(tmp_path):
    """Hash-compare skip and `diff -r` auditability both depend on this."""
    vault, ws = make_vault(tmp_path), make_workspace(tmp_path)
    mirror_vault.mirror(vault, ws)
    rel = "13 - Resources/Jobs/Ship a Change.md"
    assert (ws / "memory" / "vault" / rel).read_bytes() == (vault / rel).read_bytes()


def test_second_run_is_a_no_op(tmp_path):
    vault, ws = make_vault(tmp_path), make_workspace(tmp_path)
    first = mirror_vault.mirror(vault, ws)
    second = mirror_vault.mirror(vault, ws)
    assert first["copied"] > 0
    assert second["copied"] == 0
    assert second["unchanged"] == first["copied"]
    assert second["pruned"] == 0


def test_edited_note_is_recopied(tmp_path):
    vault, ws = make_vault(tmp_path), make_workspace(tmp_path)
    mirror_vault.mirror(vault, ws)
    rel = "00 - Inbox/Inbox.md"
    (vault / rel).write_text("# Inbox\n\nnew thought\n", encoding="utf-8")
    r = mirror_vault.mirror(vault, ws)
    assert r["copied"] == 1
    assert "new thought" in (ws / "memory" / "vault" / rel).read_text(encoding="utf-8")


def test_deleted_note_is_pruned(tmp_path):
    """Without this the index answers from notes the vault no longer has."""
    vault, ws = make_vault(tmp_path), make_workspace(tmp_path)
    mirror_vault.mirror(vault, ws)
    rel = "13 - Resources/Jobs/Ship a Change.md"
    assert rel in mirrored(ws)

    (vault / rel).unlink()
    r = mirror_vault.mirror(vault, ws)

    assert r["pruned"] == 1
    assert rel not in mirrored(ws)
    assert not (ws / "memory" / "vault" / "13 - Resources" / "Jobs").exists(), \
        "emptied directory should be tidied"


def test_a_folder_moved_to_excluded_is_pruned_out(tmp_path):
    """Reclassifying a folder as sensitive must retract what was already mirrored."""
    vault, ws = make_vault(tmp_path), make_workspace(tmp_path)
    mirror_vault.mirror(vault, ws)
    assert any(f.startswith("00 - Inbox") for f in mirrored(ws))

    mirror_vault.EXCLUDED_TOP_LEVEL.add("inbox")
    try:
        r = mirror_vault.mirror(vault, ws)
    finally:
        mirror_vault.EXCLUDED_TOP_LEVEL.discard("inbox")

    assert r["pruned"] == 1
    assert not any(f.startswith("00 - Inbox") for f in mirrored(ws))


# ── the no-vault host ──────────────────────────────────────────────────────

def test_missing_vault_exits_zero(tmp_path):
    """Every non-Linux host has no vault. Under `set -e` a non-zero exit here would
    abort sync_memory.sh before indexing the transcripts it just exported."""
    ws = make_workspace(tmp_path)
    res = run_script(tmp_path / "no-such-vault", ws)
    assert res.returncode == 0
    assert "skipped" in res.stdout
    assert corpus_roots(ws) == {"session-aaaa.md", "premortem-audit.md"}


def test_missing_vault_does_not_create_the_mirror_dir(tmp_path):
    ws = make_workspace(tmp_path)
    run_script(tmp_path / "no-such-vault", ws)
    assert not (ws / "memory" / "vault").exists()


# ── observability ──────────────────────────────────────────────────────────

def test_counts_are_reported_on_stdout(tmp_path):
    """The cron redirects stdout to state/memweave-sync.log; a partial mirror has to
    be distinguishable there from a complete one."""
    vault, ws = make_vault(tmp_path), make_workspace(tmp_path)
    res = run_script(vault, ws)
    assert res.returncode == 0
    assert "copied" in res.stdout and "pruned" in res.stdout and "failed" in res.stdout


def test_unreadable_note_fails_loudly_without_starving_the_rest(tmp_path):
    """One bad note must not keep every good one out of the index — but the run
    still has to report itself unsuccessful, or 'resilient' degrades into 'silent'."""
    vault, ws = make_vault(tmp_path), make_workspace(tmp_path)
    bad = vault / "00 - Inbox" / "Inbox.md"
    bad.unlink()
    bad.mkdir()  # a directory named *.md — read_bytes raises, rglob still yields it

    r = mirror_vault.mirror(vault, ws)

    assert r["failed"] == 1
    assert r["copied"] >= 4, "the other notes still mirrored"

    res = run_script(vault, ws)
    assert res.returncode == 1
    assert "FAILED" in res.stderr

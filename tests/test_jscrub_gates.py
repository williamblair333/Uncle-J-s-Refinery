"""jscrub automation: the pre-commit staged-file scan and the audit's live canary.

precommit-scan.sh must block a commit whose staged text carries invisible Unicode,
judge the staged blob rather than the working tree, and never rewrite anything.
audit-repo.sh must fail loudly when the detector stops detecting.
"""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN = REPO_ROOT / "scripts" / "jscrub" / "precommit-scan.sh"
AUDIT = REPO_ROOT / "scripts" / "jscrub" / "audit-repo.sh"
ZWSP = "\u200b"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    return repo


def scan(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCAN)], cwd=repo, capture_output=True, text=True,
                          env={**os.environ, "TMPDIR": str(repo.parent)})


def test_nothing_staged_passes(tmp_path):
    assert scan(make_repo(tmp_path)).returncode == 0


def test_clean_staged_file_passes(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "a.md").write_text("plain text\n")
    git(repo, "add", "a.md")
    assert scan(repo).returncode == 0


def test_invisible_unicode_blocks_and_file_is_untouched(tmp_path):
    repo = make_repo(tmp_path)
    f = repo / "docs" / "a.md"
    f.parent.mkdir()
    data = f"hid{ZWSP}den\n".encode()
    f.write_bytes(data)
    git(repo, "add", "docs/a.md")
    r = scan(repo)
    assert r.returncode == 1
    assert "commit blocked" in r.stderr
    assert f.read_bytes() == data  # report-only: never rewritten
    assert not list(f.parent.glob("*.bak*"))


def test_staged_blob_is_judged_not_working_tree(tmp_path):
    repo = make_repo(tmp_path)
    f = repo / "a.py"
    f.write_text(f"x = 1  # {ZWSP}\n")
    git(repo, "add", "a.py")
    f.write_text("x = 1\n")  # cleaned on disk but not re-staged
    assert scan(repo).returncode == 1


def test_untracked_extension_is_not_scanned(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "blob.bin").write_bytes(f"a{ZWSP}b".encode())
    git(repo, "add", "blob.bin")
    assert scan(repo).returncode == 0


def test_fixture_excluded_by_pathspec(tmp_path):
    repo = make_repo(tmp_path)
    f = repo / "tests" / "test_tg_security.py"
    f.parent.mkdir()
    f.write_text(f"s = '{ZWSP}'\n")
    git(repo, "add", "tests/test_tg_security.py")
    assert scan(repo).returncode == 0


def test_audit_canary_fails_when_detector_is_broken(tmp_path):
    broken = tmp_path / "jscrub"
    broken.write_text("#!/usr/bin/env bash\nexit 0\n")  # detects nothing, ever
    broken.chmod(0o755)
    r = subprocess.run(["bash", str(AUDIT)], capture_output=True, text=True,
                       env={**os.environ, "JSCRUB_BIN": str(broken), "TMPDIR": str(tmp_path)})
    assert r.returncode == 3
    assert "canary not detected" in r.stderr

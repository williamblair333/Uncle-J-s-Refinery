"""index_workspace.py must EXIT when the memweave db is locked, not hang.

2026-11-02: the boot catch-up's sync hit `sqlite3.OperationalError: database is
locked` in MemWeave.__aenter__ (schema check). __aexit__ never ran, so the aiosqlite
connection was never closed, and its non-daemon worker thread kept the interpreter
alive holding /tmp/memweave-sync.lock.d for 2 h. This reproduces it for real: hold an
exclusive lock on the store, run the indexer, and require it to exit nonzero promptly.

Needs .venv-memweave; skipped where it isn't installed.
"""

import sqlite3
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PY = REPO / ".venv-memweave" / "bin" / "python"
SCRIPT = REPO / "scripts" / "memweave" / "index_workspace.py"

pytestmark = pytest.mark.skipif(not PY.exists(), reason=".venv-memweave not installed")


def index(workspace: Path, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run([str(PY), str(SCRIPT), "--workspace", str(workspace)],
                          capture_output=True, text=True, timeout=timeout)


def test_locked_store_exits_instead_of_hanging(tmp_path):
    ws = tmp_path / "ws"
    (ws / "memory").mkdir(parents=True)
    (ws / "memory" / "note.md").write_text("# note\n\nhello lock test\n")
    first = index(ws, timeout=180)
    assert first.returncode == 0, first.stderr[-2000:]
    dbs = [p for p in ws.rglob("*") if p.suffix in (".sqlite", ".db", ".sqlite3")]
    assert len(dbs) == 1, dbs

    holder = sqlite3.connect(str(dbs[0]), timeout=0)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        # sqlite's default busy timeout is 5 s; the hang was unbounded. 90 s is ample.
        try:
            second = index(ws, timeout=90)
        except subprocess.TimeoutExpired:
            pytest.fail("index_workspace.py hung on a locked store (the 2026-11-02 bug)")
    finally:
        holder.rollback()
        holder.close()
    assert second.returncode != 0
    assert "database is locked" in second.stderr

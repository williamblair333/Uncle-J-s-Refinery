"""hook_log_append: the shared writer for state/hook-blocks.log (2026-10-22).

Two defects it closes:
  * The log held 209 NUL bytes, so GNU grep classed it as binary and printed
    nothing — a reviewer following the documented `grep` step read silence as
    "no blocks". `head -c` truncation also left half a UTF-8 character, which GNU
    grep treats the same way. The writer now emits text only, one record per line.
  * The log had no rotation. It is not reconstructible, so rotation ARCHIVES
    (rename to <log>.YYYYMMDD) and never truncates.

The function is inlined in every hook that writes the log (a sourced library that
went missing would fail open), so the first test pins the copies identical.
pytest + bash. No API calls.
"""

import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WRITERS = [
    REPO_ROOT / "hooks" / "discipline" / "grep-guard.sh",
    REPO_ROOT / "hooks" / "discipline" / "edit-surface-guard.sh",
    REPO_ROOT / "hooks" / "pre-mortem-guard" / "surface-write-guard.sh",
]
SURFACE_GUARD = REPO_ROOT / "hooks" / "pre-mortem-guard" / "surface-write-guard.sh"
BLOCK_RE = re.compile(r"^# >>> hook_log_append.*?^# <<< hook_log_append$", re.S | re.M)


def _block(path: Path) -> str:
    m = BLOCK_RE.search(path.read_text(encoding="utf-8"))
    assert m, f"{path.name}: hook_log_append block missing"
    return m.group(0)


def test_every_writer_carries_the_identical_function():
    blocks = {p.name: _block(p) for p in WRITERS}
    first = blocks[WRITERS[0].name]
    drift = [name for name, b in blocks.items() if b != first]
    assert not drift, f"hook_log_append drifted in: {drift}"


def test_no_writer_appends_to_the_log_directly():
    """Every append must go through the sanitising, rotating writer."""
    for p in WRITERS:
        body = BLOCK_RE.sub("", p.read_text(encoding="utf-8"))
        assert not re.search(r'>>\s*"\$LOG"', body), f"{p.name} still appends to $LOG directly"


def append(tmp_path: Path, rec: bytes, max_bytes: int | None = None,
           log: Path | None = None) -> subprocess.CompletedProcess:
    log = log or tmp_path / "hook-blocks.log"
    script = _block(WRITERS[0]) + '\nhook_log_append "$1" "$2"\n'
    env = {**os.environ}
    if max_bytes is not None:
        env["HOOK_LOG_MAX_BYTES"] = str(max_bytes)
    return subprocess.run([b"bash", b"-c", script.encode(), b"hook", str(log).encode(), rec],
                          capture_output=True, env=env, timeout=30)


def archives(tmp_path: Path) -> list[Path]:
    return sorted(p for p in tmp_path.iterdir()
                  if p.name.startswith("hook-blocks.log.") and not p.name.endswith(".lock"))


# ── text only, one record per line ───────────────────────────────────────────

def test_control_bytes_become_spaces_and_one_line_is_written(tmp_path):
    append(tmp_path, b"2026 BLOCKED a\x01b\x1b[31mc\x7fd\te\rf\ng session=s")
    raw = (tmp_path / "hook-blocks.log").read_bytes()
    assert raw.count(b"\n") == 1 and raw.endswith(b"\n")
    assert not re.search(rb"[\x00-\x09\x0b-\x1f\x7f]", raw), raw
    assert b"session=s" in raw


def test_utf8_fragment_from_head_c_is_dropped(tmp_path):
    # `head -c` cut an em dash (e2 80 94) after two bytes: invalid UTF-8.
    append(tmp_path, b"2026 BLOCKED cmd=abc \xe2\x80 session=s")
    raw = (tmp_path / "hook-blocks.log").read_bytes()
    raw.decode("utf-8")  # raises if invalid
    assert raw == b"2026 BLOCKED cmd=abc  session=s\n"


def test_valid_utf8_is_kept(tmp_path):
    append(tmp_path, "2026 BLOCKED cmd=a — b session=s".encode())
    assert (tmp_path / "hook-blocks.log").read_text(encoding="utf-8") == \
        "2026 BLOCKED cmd=a — b session=s\n"


def test_log_stays_text_to_grep(tmp_path):
    append(tmp_path, b"2026-10-22 BLOCKED x\x01\xe2\x80 session=s")
    res = subprocess.run(["grep", "-c", "2026-10-22", str(tmp_path / "hook-blocks.log")],
                         capture_output=True, text=True,
                         env={**os.environ, "LC_ALL": "C.UTF-8"})
    assert res.stdout.strip() == "1", res


def test_guard_entry_with_control_chars_is_clean(tmp_path):
    """End to end through a real hook: a blocked command full of control bytes."""
    log = tmp_path / "hook-blocks.log"
    cmd = "echo \u0001\u001b[0m\u007f — x > /opt/proj/x/scripts/a.sh"
    subprocess.run(["bash", str(SURFACE_GUARD)],
                   input=json.dumps({"tool_input": {"command": cmd}, "session_id": "s1"}),
                   capture_output=True, text=True, timeout=30,
                   env={**os.environ, "SURFACE_GUARD_LOG": str(log)})
    raw = log.read_bytes()
    assert raw.count(b"\n") == 1
    assert not re.search(rb"[\x00-\x09\x0b-\x1f\x7f]", raw), raw
    raw.decode("utf-8")
    assert b"session=s1" in raw


# ── rotation archives, never truncates ───────────────────────────────────────

def test_no_rotation_under_the_limit(tmp_path):
    log = tmp_path / "hook-blocks.log"
    log.write_bytes(b"old\n")
    append(tmp_path, b"new", max_bytes=1000)
    assert log.read_bytes() == b"old\nnew\n"
    assert archives(tmp_path) == []


def test_over_limit_archives_whole_file_and_starts_fresh(tmp_path):
    log = tmp_path / "hook-blocks.log"
    old = b"".join(b"line %d\n" % i for i in range(50))
    log.write_bytes(old)
    append(tmp_path, b"new", max_bytes=100)
    arch = archives(tmp_path)
    assert len(arch) == 1
    assert re.fullmatch(r"hook-blocks\.log\.\d{8}", arch[0].name), arch[0].name
    assert arch[0].read_bytes() == old, "archive must hold the old log byte for byte"
    assert log.read_bytes() == b"new\n"
    assert not (tmp_path / "hook-blocks.log.rotate.lock").exists()


def test_existing_archive_is_never_overwritten(tmp_path):
    log = tmp_path / "hook-blocks.log"
    today = time.strftime("%Y%m%d")
    first = tmp_path / f"hook-blocks.log.{today}"
    first.write_bytes(b"first archive\n")
    log.write_bytes(b"x" * 200 + b"\n")
    append(tmp_path, b"new", max_bytes=100)
    assert first.read_bytes() == b"first archive\n"
    arch = archives(tmp_path)
    assert len(arch) == 2
    second = [a for a in arch if a != first][0]
    assert re.fullmatch(rf"hook-blocks\.log\.{today}-\d{{6}}-\d+", second.name), second.name
    assert second.read_bytes() == b"x" * 200 + b"\n"
    assert log.read_bytes() == b"new\n"


def test_fresh_lock_skips_rotation_but_still_appends(tmp_path):
    log = tmp_path / "hook-blocks.log"
    log.write_bytes(b"x" * 200 + b"\n")
    (tmp_path / "hook-blocks.log.rotate.lock").mkdir()
    append(tmp_path, b"new", max_bytes=100)
    assert archives(tmp_path) == []
    assert log.read_bytes().endswith(b"new\n")


def test_stale_lock_is_broken(tmp_path):
    log = tmp_path / "hook-blocks.log"
    log.write_bytes(b"x" * 200 + b"\n")
    lock = tmp_path / "hook-blocks.log.rotate.lock"
    lock.mkdir()
    old = time.time() - 300
    os.utime(lock, (old, old))
    append(tmp_path, b"new", max_bytes=100)
    assert len(archives(tmp_path)) == 1
    assert log.read_bytes() == b"new\n"
    assert not lock.exists()


def test_concurrent_appends_lose_nothing(tmp_path):
    """Many hooks at once across a rotation: every record lands exactly once."""
    log = tmp_path / "hook-blocks.log"
    seed = [f"seed {i}" for i in range(40)]
    log.write_text("".join(s + "\n" for s in seed))
    recs = [f"rec {i:03d} session=s" for i in range(60)]
    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(lambda r: append(tmp_path, r.encode(), max_bytes=300), recs))
    lines = []
    for p in archives(tmp_path) + [log]:
        lines += p.read_text(encoding="utf-8").splitlines()
    assert sorted(lines) == sorted(seed + recs)
    assert archives(tmp_path), "the size limit should have forced at least one rotation"
    assert not (tmp_path / "hook-blocks.log.rotate.lock").exists()

"""Regression tests for scripts/vault-session-check.sh.

The script is a Stop hook: it asserts that a vault session was checkpointed and
warns loudly when it was not. Two properties matter more than the assertions
themselves and are pinned here:

  * It ALWAYS exits 0. A Stop hook that exits non-zero can trap session teardown.
  * It never emits note content or git file names. The vault holds a
    personal-context note and an archive with a plaintext credential.

Each case builds a real vault (a git repo with a real daily note) and a real
JSONL transcript, so the midnight-rollover behaviour is exercised against the
same code path production uses. No API calls.
"""

import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "vault-session-check.sh"
NOTES_SUBDIR = "01 - Daily Notes"

SECRET = "SUPERSECRET-VAULT-CREDENTIAL-abc123"


# ── helpers ──────────────────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )


def make_vault(tmp_path: Path, note_date: str | None, body: str = "## Session 1 - work\n",
               commit: bool = True) -> Path:
    """Build a vault git repo, optionally containing a daily note."""
    vault = tmp_path / "brain"
    (vault / NOTES_SUBDIR).mkdir(parents=True)
    _git_init(vault)

    if note_date:
        month_dir = vault / NOTES_SUBDIR / "08 - August 2026"
        month_dir.mkdir(parents=True, exist_ok=True)
        (month_dir / f"{note_date}.md").write_text(body, encoding="utf-8")

    # Always have at least one file so the repo has a HEAD.
    (vault / "README.md").write_text("vault\n", encoding="utf-8")
    if commit:
        _git(vault, "add", "-A")
        _git(vault, "commit", "-q", "-m", "init")
    return vault


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True,
                   capture_output=True)


def make_transcript(tmp_path: Path, start: datetime) -> Path:
    """Write a JSONL transcript whose first record carries `start`."""
    path = tmp_path / "transcript.jsonl"
    records = [
        {"type": "user", "timestamp": start.isoformat()},
        {"type": "assistant", "timestamp": (start + timedelta(minutes=5)).isoformat()},
    ]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def run_check(vault: Path, transcript: Path | None = None, stack_root: Path | None = None,
              env_extra: dict | None = None) -> subprocess.CompletedProcess:
    payload = {"session_id": "test-session-0001"}
    if transcript is not None:
        payload["transcript_path"] = str(transcript)

    env = {**os.environ, "VAULT_ROOT": str(vault)}
    if stack_root is not None:
        env["STACK_ROOT"] = str(stack_root)
    env.pop("VAULT_CHECK_SKIP", None)
    if env_extra:
        env.update(env_extra)

    return subprocess.run(
        ["bash", str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def logfile(stack_root: Path) -> str:
    p = stack_root / "state" / "vault-check.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ── exit-code invariant ──────────────────────────────────────────────────────

@pytest.mark.parametrize("scenario", ["clean", "no_note", "no_heading", "dirty"])
def test_always_exits_zero(tmp_path, scenario):
    """A Stop hook that exits non-zero can trap session teardown."""
    stack = tmp_path / "stack"
    start = datetime(2026, 8, 15, 20, 45, tzinfo=timezone.utc).astimezone()

    if scenario == "no_note":
        vault = make_vault(tmp_path, None)
    elif scenario == "no_heading":
        vault = make_vault(tmp_path, "2026-08-15", body="just prose, no heading\n")
    else:
        vault = make_vault(tmp_path, "2026-08-15")

    if scenario == "dirty":
        (vault / "untracked.md").write_text("uncommitted\n", encoding="utf-8")

    res = run_check(vault, make_transcript(tmp_path, start), stack)
    assert res.returncode == 0, f"{scenario} exited {res.returncode}: {res.stderr}"


def test_missing_vault_is_silent(tmp_path):
    """Other machines have no vault — the hook must be a no-op, not a warning."""
    res = run_check(tmp_path / "does-not-exist", None, tmp_path / "stack")
    assert res.returncode == 0
    assert res.stderr.strip() == ""


def test_skip_env_disables(tmp_path):
    vault = make_vault(tmp_path, None)
    res = run_check(vault, None, tmp_path / "stack", env_extra={"VAULT_CHECK_SKIP": "1"})
    assert res.returncode == 0
    assert res.stderr.strip() == ""


def test_no_stdin_does_not_hang(tmp_path):
    """`cat` with no stdin would block forever and hang session teardown."""
    vault = make_vault(tmp_path, None)
    res = subprocess.run(
        ["bash", str(SCRIPT)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env={**os.environ, "VAULT_ROOT": str(vault), "STACK_ROOT": str(tmp_path / "stack")},
        timeout=30,
    )
    assert res.returncode == 0


# ── the three assertions ─────────────────────────────────────────────────────

def test_clean_session_passes(tmp_path):
    stack = tmp_path / "stack"
    start = datetime(2026, 8, 15, 20, 45, tzinfo=timezone.utc).astimezone()
    vault = make_vault(tmp_path, "2026-08-15")
    # Note must be newer than session start.
    note = next((vault / NOTES_SUBDIR).rglob("2026-08-15.md"))
    os.utime(note, (time.time(), time.time()))

    res = run_check(vault, make_transcript(tmp_path, start), stack)
    assert "VAULT SESSION NOT CHECKPOINTED" not in res.stderr
    assert "PASS vault-session-check" in logfile(stack)


def test_missing_daily_note_warns(tmp_path):
    stack = tmp_path / "stack"
    start = datetime(2026, 8, 15, 20, 45, tzinfo=timezone.utc).astimezone()
    vault = make_vault(tmp_path, None)

    res = run_check(vault, make_transcript(tmp_path, start), stack)
    assert "VAULT SESSION NOT CHECKPOINTED" in res.stderr
    assert "no-daily-note" in logfile(stack)


def test_note_without_session_heading_warns(tmp_path):
    stack = tmp_path / "stack"
    start = datetime(2026, 8, 15, 20, 45, tzinfo=timezone.utc).astimezone()
    vault = make_vault(tmp_path, "2026-08-15", body="# 2026-08-15\n\nsome prose\n")

    res = run_check(vault, make_transcript(tmp_path, start), stack)
    assert "no-session-entry" in logfile(stack)
    assert "VAULT SESSION NOT CHECKPOINTED" in res.stderr


def test_note_untouched_this_session_warns(tmp_path):
    """A note carrying only YESTERDAY's entries must not satisfy today's session."""
    stack = tmp_path / "stack"
    start = datetime.now().astimezone()
    date_str = start.strftime("%Y-%m-%d")
    vault = make_vault(tmp_path, None)
    month_dir = vault / NOTES_SUBDIR / "08 - August 2026"
    month_dir.mkdir(parents=True, exist_ok=True)
    note = month_dir / f"{date_str}.md"
    note.write_text("## Session 1 - earlier today\n", encoding="utf-8")
    _git(vault, "add", "-A")
    _git(vault, "commit", "-q", "-m", "note")

    # Backdate the note to well before the session started.
    old = start.timestamp() - 7200
    os.utime(note, (old, old))

    res = run_check(vault, make_transcript(tmp_path, start), stack)
    assert "stale-session-entry" in logfile(stack)
    assert "VAULT SESSION NOT CHECKPOINTED" in res.stderr


def test_dirty_vault_warns(tmp_path):
    stack = tmp_path / "stack"
    start = datetime.now().astimezone()
    date_str = start.strftime("%Y-%m-%d")
    vault = make_vault(tmp_path, None)
    month_dir = vault / NOTES_SUBDIR / "08 - August 2026"
    month_dir.mkdir(parents=True, exist_ok=True)
    (month_dir / f"{date_str}.md").write_text("## Session 1 - work\n", encoding="utf-8")
    _git(vault, "add", "-A")
    _git(vault, "commit", "-q", "-m", "note")

    (vault / "uncommitted.md").write_text("dirty\n", encoding="utf-8")

    res = run_check(vault, make_transcript(tmp_path, start), stack)
    assert "vault-dirty" in logfile(stack)
    assert "VAULT SESSION NOT CHECKPOINTED" in res.stderr


def test_non_git_vault_warns(tmp_path):
    stack = tmp_path / "stack"
    vault = tmp_path / "brain"
    (vault / NOTES_SUBDIR).mkdir(parents=True)
    res = run_check(vault, None, stack)
    assert "vault-not-a-repo" in logfile(stack)


# ── midnight rollover: the reason the date comes from the transcript ─────────

def test_session_spanning_midnight_uses_session_start_date(tmp_path):
    """A session that began yesterday must be checked against YESTERDAY's note.

    Wall-clock `date +%F` at hook time would look for a note dated today,
    find nothing, and warn on every late-night session.
    """
    stack = tmp_path / "stack"
    start = datetime.now().astimezone() - timedelta(days=1)
    yesterday = start.strftime("%Y-%m-%d")

    vault = make_vault(tmp_path, None)
    month_dir = vault / NOTES_SUBDIR / "08 - August 2026"
    month_dir.mkdir(parents=True, exist_ok=True)
    note = month_dir / f"{yesterday}.md"
    note.write_text("## Session 1 - late night\n", encoding="utf-8")
    _git(vault, "add", "-A")
    _git(vault, "commit", "-q", "-m", "note")
    os.utime(note, (time.time(), time.time()))

    res = run_check(vault, make_transcript(tmp_path, start), stack)
    log = logfile(stack)
    assert f"date={yesterday}" in log, "did not use the session-start date"
    assert "src=transcript" in log
    assert "no-daily-note" not in log
    assert "VAULT SESSION NOT CHECKPOINTED" not in res.stderr


def test_falls_back_to_wall_clock_without_transcript(tmp_path):
    stack = tmp_path / "stack"
    vault = make_vault(tmp_path, None)
    res = run_check(vault, None, stack)
    assert res.returncode == 0
    assert "src=wall-clock" in logfile(stack)


# ── content must never leak ──────────────────────────────────────────────────

def test_note_content_never_reaches_stderr_or_log(tmp_path):
    """The vault holds a plaintext credential; warnings carry counts, not content."""
    stack = tmp_path / "stack"
    start = datetime.now().astimezone()
    date_str = start.strftime("%Y-%m-%d")

    vault = make_vault(tmp_path, None)
    month_dir = vault / NOTES_SUBDIR / "08 - August 2026"
    month_dir.mkdir(parents=True, exist_ok=True)
    # A note with no session heading, whose body is sensitive.
    (month_dir / f"{date_str}.md").write_text(f"password: {SECRET}\n", encoding="utf-8")

    res = run_check(vault, make_transcript(tmp_path, start), stack)

    assert SECRET not in res.stderr
    assert SECRET not in res.stdout
    assert SECRET not in logfile(stack)


def test_dirty_filenames_never_reach_stderr_or_log(tmp_path):
    """`git status --porcelain` is reduced to a count before any message."""
    stack = tmp_path / "stack"
    start = datetime.now().astimezone()
    date_str = start.strftime("%Y-%m-%d")

    vault = make_vault(tmp_path, None)
    month_dir = vault / NOTES_SUBDIR / "08 - August 2026"
    month_dir.mkdir(parents=True, exist_ok=True)
    (month_dir / f"{date_str}.md").write_text("## Session 1 - work\n", encoding="utf-8")
    _git(vault, "add", "-A")
    _git(vault, "commit", "-q", "-m", "note")

    leaky = "Personal-Context-DO-NOT-DISCLOSE.md"
    (vault / leaky).write_text("private\n", encoding="utf-8")

    res = run_check(vault, make_transcript(tmp_path, start), stack)

    assert "vault-dirty" in logfile(stack)
    assert leaky not in res.stderr
    assert leaky not in logfile(stack)


# ── the log is the audit trail ───────────────────────────────────────────────

def test_every_run_writes_exactly_one_log_line(tmp_path):
    """A checker whose outcome goes unrecorded can't be distinguished from a pass.

    Also pins the defect this whole session started from: multi-line content must
    not spill across physical log lines.
    """
    stack = tmp_path / "stack"
    start = datetime.now().astimezone()
    vault = make_vault(tmp_path, None)

    for _ in range(3):
        run_check(vault, make_transcript(tmp_path, start), stack)

    lines = [ln for ln in logfile(stack).splitlines() if ln.strip()]
    assert len(lines) == 3, f"expected 3 log lines, got {len(lines)}"
    for ln in lines:
        assert ln.startswith("20"), f"continuation junk in log: {ln!r}"
        assert "session=" in ln, f"line missing session=: {ln!r}"

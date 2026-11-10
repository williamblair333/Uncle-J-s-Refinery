"""Tests for scripts/tool_miner.py: mining recurring tools from Claude transcripts."""

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "tool_miner.py"

spec = importlib.util.spec_from_file_location("tool_miner", SCRIPT_PATH)
tm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tm)


# ── shape_of tests ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "cmd,expected",
    [
        ("git commit -m x", "git commit"),
        ("docker compose up -d", "docker compose"),
        ("python3 scripts/a.py --x", "python3 a.py"),
        ("opt/bin/docker compose up -d", "docker compose"),
        ("sudo FOO=1 git commit -m x", "git commit"),
        ("cd somedir && ls", ""),
        # Consecutive duplicate collapse
        ("git commit -m 1 && git commit -m 2", "git commit"),
        # Trivial two-word heads
        ("git status", ""),
        ("git log -n 5", ""),
        ("git diff HEAD", ""),
        ("git show abc1234", ""),
        ("git fetch origin", ""),
        # Trivial single-word heads
        ("ls -la", ""),
        ("cat file.txt", ""),
        ("echo 'hello'", ""),
        ("pwd", ""),
        # Multiple non-trivial segments
        ("python3 test.py && docker compose up -d", "python3 test.py && docker compose"),
    ],
)
def test_shape_of_normalization(cmd: str, expected: str):
    assert tm.shape_of(cmd) == expected


# ── mine() counting across 2 projects x 3 sessions ───────────────────────────

def _make_transcript_line(command: str) -> str:
    return json.dumps({
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": command}}
            ]
        },
    }) + "\n"


def test_mine_counts_distinct_sessions_and_projects(tmp_path: Path):
    root = tmp_path / "projects"
    p1 = root / "proj_alpha"
    p2 = root / "proj_beta"
    p1.mkdir(parents=True)
    p2.mkdir(parents=True)

    # 3 sessions in proj_alpha
    (p1 / "sess1.jsonl").write_text(
        _make_transcript_line("git commit -m 'first'")
        + _make_transcript_line("git commit -m 'second'"),  # duplicate shape in same session
        encoding="utf-8",
    )
    (p1 / "sess2.jsonl").write_text(
        _make_transcript_line("git commit -m 'third'"),
        encoding="utf-8",
    )
    (p1 / "sess3.jsonl").write_text(
        _make_transcript_line("git commit -m 'fourth'"),
        encoding="utf-8",
    )

    # 3 sessions in proj_beta
    (p2 / "sess4.jsonl").write_text(
        _make_transcript_line("git commit -m 'fifth'")
        + _make_transcript_line("docker compose up -d"),
        encoding="utf-8",
    )
    (p2 / "sess5.jsonl").write_text(
        _make_transcript_line("git commit -m 'sixth'"),
        encoding="utf-8",
    )
    (p2 / "sess6.jsonl").write_text(
        _make_transcript_line("git commit -m 'seventh'"),
        encoding="utf-8",
    )

    results = tm.mine(root, since_days=0)
    assert len(results) == 2

    # git commit appears in all 6 sessions across 2 projects, used 7 times
    git_commit_item = next(r for r in results if r["shape"] == "git commit")
    assert git_commit_item["sessions"] == 6
    assert git_commit_item["projects"] == 2
    assert git_commit_item["uses"] == 7
    assert git_commit_item["example"] == "git commit -m 'first'"

    # docker compose appears only in 1 session, 1 project, 1 use
    docker_item = next(r for r in results if r["shape"] == "docker compose")
    assert docker_item["sessions"] == 1
    assert docker_item["projects"] == 1
    assert docker_item["uses"] == 1
    assert docker_item["example"] == "docker compose up -d"


# ── CLI --min-sessions filter via main ────────────────────────────────────────

def test_main_min_sessions_filter_json(tmp_path: Path, capsys: pytest.CaptureFixture):
    root = tmp_path / "projects"
    p1 = root / "p1"
    p2 = root / "p2"
    p1.mkdir(parents=True)
    p2.mkdir(parents=True)

    # Tool A appears in 2 sessions (one in p1, one in p2)
    (p1 / "s1.jsonl").write_text(_make_transcript_line("git commit -m 1"), encoding="utf-8")
    (p2 / "s2.jsonl").write_text(_make_transcript_line("git commit -m 2"), encoding="utf-8")

    # Tool B appears in only 1 session
    (p1 / "s3.jsonl").write_text(_make_transcript_line("docker compose up -d"), encoding="utf-8")

    # Run with --min-sessions 2
    ret = tm.main([
        "--root", str(root),
        "--json",
        "--min-sessions", "2",
        "--since-days", "0",
        "--min-steps", "1",
    ])
    assert ret == 0

    out = capsys.readouterr().out
    data = json.loads(out)
    shapes = [item["shape"] for item in data]

    assert "git commit" in shapes
    assert "docker compose" not in shapes


# ── unparseable and bad jsonl lines are skipped ──────────────────────────────

def test_bad_jsonl_lines_skipped(tmp_path: Path):
    root = tmp_path / "projects"
    p = root / "p1"
    p.mkdir(parents=True)

    content = "\n".join([
        "not json at all {{{",
        "42",
        json.dumps({"type": "user", "message": "hello"}),
        json.dumps({"type": "assistant", "message": "not-a-dict"}),
        json.dumps({"type": "assistant", "message": {"content": "not-a-list"}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "git commit -m valid"}}]}}),
        "",
    ])
    (p / "sess.jsonl").write_text(content, encoding="utf-8")

    results = tm.mine(root, since_days=0)
    assert len(results) == 1
    assert results[0]["shape"] == "git commit"
    assert results[0]["uses"] == 1


# ── missing root returns 2 ───────────────────────────────────────────────────

def test_missing_root_returns_2(tmp_path: Path, capsys: pytest.CaptureFixture):
    missing_dir = tmp_path / "does_not_exist"
    ret = tm.main(["--root", str(missing_dir)])
    assert ret == 2
    err = capsys.readouterr().err
    assert "does not exist" in err.lower()


# ── table formatting and since-days filter ────────────────────────────────────

def test_main_table_output(tmp_path: Path, capsys: pytest.CaptureFixture):
    root = tmp_path / "projects"
    p = root / "p1"
    p.mkdir(parents=True)
    (p / "sess.jsonl").write_text(_make_transcript_line("python3 scripts/a.py --x"), encoding="utf-8")

    ret = tm.main(["--root", str(root), "--min-sessions", "1", "--since-days", "0",
                   "--min-steps", "1", "--include-tools"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Sessions" in out
    assert "Shape" in out
    assert "python3 a.py" in out


def test_since_days_filter(tmp_path: Path):
    root = tmp_path / "projects"
    p = root / "p1"
    p.mkdir(parents=True)

    old_file = p / "old.jsonl"
    old_file.write_text(_make_transcript_line("git commit -m old"), encoding="utf-8")
    # Set mtime to 60 days ago
    sixty_days_ago = time.time() - (60 * 86400)
    os.utime(old_file, (sixty_days_ago, sixty_days_ago))

    new_file = p / "new.jsonl"
    new_file.write_text(_make_transcript_line("docker compose up -d"), encoding="utf-8")

    results = tm.mine(root, since_days=30)
    shapes = [r["shape"] for r in results]
    assert "docker compose" in shapes
    assert "git commit" not in shapes


def test_quotes_heredocs_and_redirects_are_not_steps():
    commit = 'git add a && git commit -q -m "x\n\nCo-Authored-By: C <n@x.com>" && git push'
    assert tm.shape_of(commit) == "git add && git commit && git push"
    heredoc = "python3 - <<'EOF'\nimport os\nprint(1)\nEOF\ngh pr list"
    assert tm.shape_of(heredoc) == "python3 && gh pr"
    assert tm.shape_of("timeout 600 pytest -q 2>&1 | tail -3") == "pytest"
    assert tm.shape_of("grep -E 'a|b|c' f && gh run list") == "gh run"
    assert tm.shape_of("for f in a b; do gh api x; done") == "gh api"


def test_tool_calls_and_one_step_shapes_are_dropped(tmp_path, capsys):
    root = tmp_path / "projects"
    for n in range(3):
        d = root / f"p{n}"
        d.mkdir(parents=True)
        (d / "s.jsonl").write_text(
            _make_transcript_line("just test && ./x.sh") + "\n"
            + _make_transcript_line("git push -u x && gh pr create") + "\n"
            + _make_transcript_line("docker ps"), encoding="utf-8")
    assert tm.main(["--root", str(root), "--json", "--since-days", "0"]) == 0
    shapes = [r["shape"] for r in json.loads(capsys.readouterr().out)]
    assert shapes == ["git push && gh pr"]

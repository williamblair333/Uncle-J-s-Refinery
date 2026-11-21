"""fix-guardrails-digest.sh: pinned image digests commit; bare 64-hex strings still block."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "scripts" / "fix-guardrails-digest.sh"
LIVE_HOOK = Path.home() / ".claude" / "hooks" / "scan-commit" / "scan-commit.sh"
LIVE_PATTERNS = Path.home() / ".claude" / "hooks" / "patterns" / "secrets.json"
HEX = "ab" * 32

pytestmark = pytest.mark.skipif(
    not (LIVE_HOOK.is_file() and LIVE_PATTERNS.is_file()), reason="guardrails not installed"
)


def _sandbox(tmp_path):
    hooks = tmp_path / "hooks"
    (hooks / "scan-commit").mkdir(parents=True)
    (hooks / "patterns").mkdir()
    hook = hooks / "scan-commit" / "scan-commit.sh"
    shutil.copy(LIVE_HOOK, hook)
    shutil.copy(LIVE_PATTERNS, hooks / "patterns" / "secrets.json")
    # Start from upstream text: strip a carve-out already applied on this host.
    lines = hook.read_text().splitlines(keepends=True)
    out, skip = [], 0
    for line in lines:
        if skip:
            skip -= 1
            continue
        if line.startswith("# refinery: fix-guardrails-digest"):
            skip = 2
            continue
        out.append(line)
    hook.write_text("".join(out))
    return hook


def _commit_rc(hook, tmp_path, text):
    repo = tmp_path / "r"
    repo.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "compose.yaml").write_text(text)
    subprocess.run(["git", "-C", str(repo), "add", "compose.yaml"], check=True)
    payload = json.dumps({"cwd": str(repo), "tool_input": {"command": "git commit -m x"}})
    return subprocess.run(["bash", str(hook)], input=payload, text=True,
                          capture_output=True).returncode


def test_upstream_blocks_digest_and_fix_allows_it(tmp_path):
    hook = _sandbox(tmp_path)
    pin = f"image: binwiederhier/ntfy@sha256:{HEX}\n"
    assert _commit_rc(hook, tmp_path, pin) == 2, "baseline: upstream should block a digest"
    assert subprocess.run(["bash", str(FIX), "--check", str(hook)]).returncode == 1
    subprocess.run(["bash", str(FIX), str(hook)], check=True)
    assert _commit_rc(hook, tmp_path, pin) == 0
    assert subprocess.run(["bash", str(FIX), "--check", str(hook)]).returncode == 0


def test_bare_hex_still_blocked_and_fix_idempotent(tmp_path):
    hook = _sandbox(tmp_path)
    subprocess.run(["bash", str(FIX), str(hook)], check=True)
    once = hook.read_text()
    subprocess.run(["bash", str(FIX), str(hook)], check=True)
    assert hook.read_text() == once
    assert once.count("fix-guardrails-digest") == 1
    assert _commit_rc(hook, tmp_path, f"token = {HEX}\n") == 2

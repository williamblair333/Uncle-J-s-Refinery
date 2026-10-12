"""refinery-doctor's jcodemunch-sessionstart check.

jcodemunch's compaction restore is two hooks: `hook-precompact` notes the session
before compaction, and `hook-sessionstart` (SessionStart, matcher
compact|resume|fork) injects the working-state journal afterwards. `jcodemunch-mcp
init` added the second half in a later release and only merges it on a re-run, which
also rewrites CLAUDE.md and other hooks. Hosts installed earlier therefore had the
PreCompact half alone, so nothing was ever restored. The doctor adds just that entry.

Everything runs against a temp HOME. No writes to the real ~/.claude.
"""

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCTOR = REPO_ROOT / "scripts" / "refinery-doctor.sh"
CHECK = "jcodemunch-sessionstart"
EXE = "'/opt/x/.venv/bin/jcodemunch-mcp'"


def run_doctor(home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(DOCTOR), "--check", CHECK, *args],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "HOME": str(home)},
    )


def write_settings(tmp_path: Path, hooks: dict) -> Path:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    settings = {"model": "keep-me", "hooks": hooks}
    (home / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2))
    return home


def settings_of(home: Path) -> dict:
    return json.loads((home / ".claude" / "settings.json").read_text())


def sessionstart_commands(home: Path) -> list[str]:
    return [h["command"]
            for g in settings_of(home)["hooks"].get("SessionStart", [])
            for h in g["hooks"]]


PRECOMPACT_ONLY = {
    "PreCompact": [{"matcher": "", "hooks": [{"type": "command", "command": f"{EXE} hook-precompact"}]}],
    "SessionStart": [{"hooks": [{"type": "command", "command": "/x/product-md-check.sh"}]}],
}


def test_missing_entry_is_reported_and_dry_run_writes_nothing(tmp_path):
    home = write_settings(tmp_path, PRECOMPACT_ONLY)
    before = (home / ".claude" / "settings.json").read_bytes()
    r = run_doctor(home)
    assert r.returncode == 1
    assert "MIGRATION AVAILABLE" in r.stderr
    assert (home / ".claude" / "settings.json").read_bytes() == before


def test_fix_adds_entry_with_existing_exe_and_matcher(tmp_path):
    home = write_settings(tmp_path, PRECOMPACT_ONLY)
    r = run_doctor(home, "--fix")
    assert "FIXED" in r.stderr, r.stderr
    groups = settings_of(home)["hooks"]["SessionStart"]
    added = [g for g in groups if "hook-sessionstart" in g["hooks"][0]["command"]]
    assert len(added) == 1
    assert added[0]["matcher"] == "compact|resume|fork"
    assert added[0]["hooks"][0]["command"] == f"{EXE} hook-sessionstart"


def test_fix_preserves_everything_else_and_leaves_backup(tmp_path):
    home = write_settings(tmp_path, PRECOMPACT_ONLY)
    run_doctor(home, "--fix")
    s = settings_of(home)
    assert s["model"] == "keep-me"
    assert s["hooks"]["PreCompact"] == PRECOMPACT_ONLY["PreCompact"]
    assert "/x/product-md-check.sh" in sessionstart_commands(home)
    backup = json.loads((home / ".claude" / "settings.json.bak").read_text())
    assert backup["hooks"] == PRECOMPACT_ONLY


def test_fix_is_idempotent(tmp_path):
    home = write_settings(tmp_path, PRECOMPACT_ONLY)
    run_doctor(home, "--fix")
    r = run_doctor(home, "--fix")
    assert r.returncode == 0, r.stderr
    assert sum("hook-sessionstart" in c for c in sessionstart_commands(home)) == 1


def test_no_jcodemunch_hooks_means_skip_not_install(tmp_path):
    """No jcodemunch hooks at all is an install choice, not drift."""
    hooks = {"Stop": [{"hooks": [{"type": "command", "command": "/x/stop.sh"}]}]}
    home = write_settings(tmp_path, hooks)
    r = run_doctor(home, "--fix")
    assert r.returncode == 0, r.stderr
    assert settings_of(home)["hooks"] == hooks


def test_missing_settings_file_is_skipped(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    r = run_doctor(home, "--fix")
    assert r.returncode == 0, r.stderr
    assert not (home / ".claude" / "settings.json").exists()

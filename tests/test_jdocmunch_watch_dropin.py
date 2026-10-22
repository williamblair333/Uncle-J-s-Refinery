"""jdocmunch-watch summaries-off drop-in: scripts/jdocmunch-watch-dropin.sh and the
refinery-doctor check that calls it.

`jdocmunch-mcp watch-install` rewrites the unit on every run and takes no flags
(upstream jdocmunch-mcp#120), so --no-ai-summaries lives in a drop-in that nothing
restored. Everything runs against a temp HOME with a fake `systemctl` on PATH, so
the real user units are never read, written, reloaded or restarted.
"""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "scripts" / "jdocmunch-watch-dropin.sh"
DOCTOR = REPO_ROOT / "scripts" / "refinery-doctor.sh"

UNIT = """[Unit]
Description=jdocmunch-mcp watcher

[Service]
Type=simple
ExecStart=/x/venv/bin/python3 -m jdocmunch_mcp watch
Restart=on-failure
"""


def setup(tmp_path: Path, unit: str | None = UNIT) -> tuple[Path, Path]:
    home = tmp_path / "home"
    units = home / ".config" / "systemd" / "user"
    units.mkdir(parents=True)
    if unit is not None:
        (units / "jdocmunch-watch.service").write_text(unit)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "systemctl"
    fake.write_text('#!/usr/bin/env bash\necho "$*" >> "$FAKE_LOG"\n')
    fake.chmod(0o755)
    return home, units / "jdocmunch-watch.service.d"


def env(tmp_path: Path, home: Path) -> dict:
    e = {**os.environ, "HOME": str(home), "FAKE_LOG": str(tmp_path / "systemctl.log"),
         "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}"}
    e.pop("XDG_CONFIG_HOME", None)
    return e


def helper(tmp_path, home, mode):
    return subprocess.run(["bash", str(HELPER), mode], capture_output=True, text=True,
                          timeout=30, env=env(tmp_path, home))


def systemctl_calls(tmp_path):
    log = tmp_path / "systemctl.log"
    return log.read_text().splitlines() if log.exists() else []


def test_no_unit_is_not_applicable_and_writes_nothing(tmp_path):
    home, dropin_dir = setup(tmp_path, unit=None)
    r = helper(tmp_path, home, "install")
    assert r.returncode == 0
    assert r.stdout.strip() == "no-unit"
    assert not dropin_dir.exists()
    assert systemctl_calls(tmp_path) == []


def test_check_reports_missing(tmp_path):
    home, dropin_dir = setup(tmp_path)
    r = helper(tmp_path, home, "check")
    assert r.returncode == 1
    assert r.stdout.strip() == "missing"
    assert not dropin_dir.exists()


def test_install_writes_flag_from_units_own_execstart_and_reloads(tmp_path):
    home, dropin_dir = setup(tmp_path)
    r = helper(tmp_path, home, "install")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "installed"
    body = (dropin_dir / "uncle-j-no-ai-summaries.conf").read_text()
    lines = body.splitlines()
    assert "ExecStart=" in lines
    assert "ExecStart=/x/venv/bin/python3 -m jdocmunch_mcp watch --no-ai-summaries" in lines
    assert lines.index("ExecStart=") < lines.index(
        "ExecStart=/x/venv/bin/python3 -m jdocmunch_mcp watch --no-ai-summaries")
    assert "Environment=WATCHFILES_IGNORE_PERMISSION_DENIED=1" in lines
    assert systemctl_calls(tmp_path) == ["--user daemon-reload",
                                         "--user try-restart jdocmunch-watch.service"]
    assert helper(tmp_path, home, "check").stdout.strip() == "present"


def test_install_is_idempotent(tmp_path):
    home, dropin_dir = setup(tmp_path)
    helper(tmp_path, home, "install")
    before = (dropin_dir / "uncle-j-no-ai-summaries.conf").read_bytes()
    r = helper(tmp_path, home, "install")
    assert r.stdout.strip() == "present"
    assert (dropin_dir / "uncle-j-no-ai-summaries.conf").read_bytes() == before
    assert len(systemctl_calls(tmp_path)) == 2  # only the first install reloaded


def test_existing_hand_written_override_is_respected(tmp_path):
    home, dropin_dir = setup(tmp_path)
    dropin_dir.mkdir()
    own = "[Service]\nExecStart=\nExecStart=/y/python -m jdocmunch_mcp watch --no-ai-summaries\n"
    (dropin_dir / "override.conf").write_text(own)
    r = helper(tmp_path, home, "install")
    assert r.stdout.strip() == "present"
    assert sorted(p.name for p in dropin_dir.iterdir()) == ["override.conf"]
    assert (dropin_dir / "override.conf").read_text() == own


def test_flag_already_in_unit_counts_as_present(tmp_path):
    """Upstream passthrough (#120) landing must read as fine, not missing."""
    home, dropin_dir = setup(tmp_path, UNIT.replace("watch\n", "watch --no-ai-summaries\n"))
    assert helper(tmp_path, home, "check").stdout.strip() == "present"


def test_override_without_flag_gets_ours_alongside(tmp_path):
    home, dropin_dir = setup(tmp_path)
    dropin_dir.mkdir()
    (dropin_dir / "override.conf").write_text("[Service]\nEnvironment=FOO=1\n")
    assert helper(tmp_path, home, "install").stdout.strip() == "installed"
    assert (dropin_dir / "override.conf").read_text() == "[Service]\nEnvironment=FOO=1\n"
    assert (dropin_dir / "uncle-j-no-ai-summaries.conf").exists()


def doctor(tmp_path, home, *args):
    return subprocess.run(["bash", str(DOCTOR), "--check", "jdocmunch-watch-dropin", *args],
                          capture_output=True, text=True, timeout=30, env=env(tmp_path, home))


def test_doctor_reports_then_fixes(tmp_path):
    home, dropin_dir = setup(tmp_path)
    r = doctor(tmp_path, home)
    assert r.returncode == 1
    assert "MIGRATION AVAILABLE" in r.stderr
    assert not dropin_dir.exists()
    r = doctor(tmp_path, home, "--fix")
    assert "FIXED" in r.stderr, r.stderr
    assert (dropin_dir / "uncle-j-no-ai-summaries.conf").exists()
    r = doctor(tmp_path, home)
    assert r.returncode == 0, r.stderr


def test_doctor_skips_without_unit(tmp_path):
    home, _ = setup(tmp_path, unit=None)
    r = doctor(tmp_path, home, "--fix")
    assert r.returncode == 0, r.stderr
    assert systemctl_calls(tmp_path) == []

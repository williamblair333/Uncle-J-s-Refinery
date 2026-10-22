"""refinery-doctor's mcp-scope check (formerly jcodemunch-scope).

A local- or project-scope registration of a stack server shadows the user-scope one
in that project. The old check grepped `claude mcp list` for jcodemunch only — and
that output carries no scope, so it never matched. The check now asks
`claude mcp get <name>` for each of the five stack servers.

A fake `claude` on PATH stands in for Claude Code: FAKE_SCOPES maps server -> scope
word, and `mcp remove` calls are logged with the cwd they ran in.
"""

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCTOR = REPO_ROOT / "scripts" / "refinery-doctor.sh"
SERVERS = ["jcodemunch", "jdatamunch", "jdocmunch", "serena", "duckdb"]

FAKE_CLAUDE = r"""#!/usr/bin/env bash
# fake claude: mcp get <name> / mcp remove <name> -s <scope>
if [[ "$1 $2" == "mcp get" ]]; then
    scope=User
    IFS=, read -ra pairs <<< "${FAKE_SCOPES:-}"
    for p in "${pairs[@]}"; do [[ "${p%%=*}" == "$3" ]] && scope="${p#*=}"; done
    printf '%s:\n  Scope: %s config (whatever)\n  Status: ok\n' "$3" "$scope"
    exit 0
fi
if [[ "$1 $2" == "mcp remove" ]]; then
    printf 'remove %s %s %s\n' "$3" "$5" "$PWD" >> "$FAKE_LOG"
    exit 0
fi
exit 1
"""


def run_doctor(tmp_path: Path, scopes: str, *args: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    claude = bindir / "claude"
    claude.write_text(FAKE_CLAUDE)
    claude.chmod(0o755)
    log = tmp_path / "claude.log"
    r = subprocess.run(
        ["bash", str(DOCTOR), "--check", "mcp-scope", *args],
        capture_output=True, text=True, timeout=60, cwd=REPO_ROOT,
        env={**os.environ, "HOME": str(tmp_path), "PATH": f"{bindir}:{os.environ['PATH']}",
             "FAKE_SCOPES": scopes, "FAKE_LOG": str(log)},
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return r, calls


def test_all_user_scope_is_clean(tmp_path):
    r, calls = run_doctor(tmp_path, "")
    assert r.returncode == 0, r.stderr
    assert "DOCTOR: ok" in r.stdout
    assert calls == []


def test_every_stack_server_is_checked(tmp_path):
    for name in SERVERS:
        r, _ = run_doctor(tmp_path, f"{name}=Local")
        assert r.returncode == 1, (name, r.stderr)
        assert f"{name} registered at local scope" in r.stderr


def test_project_scope_is_reported_and_dry_run_removes_nothing(tmp_path):
    r, calls = run_doctor(tmp_path, "serena=Project,duckdb=Local")
    assert r.returncode == 1
    assert "serena registered at project scope" in r.stderr
    assert "duckdb registered at local scope" in r.stderr
    assert calls == []


def test_fix_removes_from_the_right_scope_in_the_right_dir(tmp_path):
    r, calls = run_doctor(tmp_path, "jdocmunch=Local,serena=Project", "--fix")
    assert "FIXED" in r.stderr, r.stderr
    assert sorted(calls) == sorted([
        f"remove jdocmunch local {REPO_ROOT}",
        f"remove serena project {REPO_ROOT}",
    ])


def test_non_stack_servers_are_ignored(tmp_path):
    r, _ = run_doctor(tmp_path, "context7=Local,partikus=Project")
    assert r.returncode == 0, r.stderr


def test_old_check_name_still_works(tmp_path):
    bindir = tmp_path / "bin"
    run_doctor(tmp_path, "")  # creates the shim
    r = subprocess.run(
        ["bash", str(DOCTOR), "--check", "jcodemunch-scope"],
        capture_output=True, text=True, timeout=60, cwd=REPO_ROOT,
        env={**os.environ, "HOME": str(tmp_path), "PATH": f"{bindir}:{os.environ['PATH']}",
             "FAKE_SCOPES": "jcodemunch=Local", "FAKE_LOG": str(tmp_path / "x.log")},
    )
    assert r.returncode == 1
    assert "jcodemunch registered at local scope" in r.stderr

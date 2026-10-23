"""run_index_local (scripts/lib/jdocmunch-index-local.sh) — the CLI route.

The function used to call jdocmunch's Python API and fall back to the CLI. It now
calls only the CLI, which exits 0 even when it reports {"success": false}, so the
verdict must come from the JSON. A stub CLI records its argv and prints whatever
the test asks for; nothing touches a real index.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB = REPO_ROOT / "scripts" / "lib" / "jdocmunch-index-local.sh"

STUB = """#!/usr/bin/env bash
printf '%s\\n' "$@" > "$ARGV_FILE"
printf '%s' "$STUB_STDOUT"
exit "${STUB_RC:-0}"
"""

HARNESS = r"""
set -uo pipefail
JDOCMUNCH="$1"; PY="$2"; LOG="$3"; ROOT="$4"; LOCAL_ONLY="$5"
log() { printf '%s\n' "$*" >> "$LOG"; }
canonical_root() { printf '%s' "${1%/}"; }
is_local_only() { [[ "$LOCAL_ONLY" == 1 ]]; }
declare -A LOCAL_ONLY_IGNORE=( ["$ROOT"]=$'secret/a.md\nsecret dir/b.md' )
source "$6"
run_index_local "$ROOT" probe
"""


def run(tmp_path: Path, stdout: str, rc: int = 0, local_only: bool = False):
    stub = tmp_path / "jdocmunch-mcp"
    stub.write_text(STUB)
    stub.chmod(0o755)
    argv_file = tmp_path / "argv"
    log = tmp_path / "log"
    root = str(tmp_path / "root")
    proc = subprocess.run(
        ["bash", "-c", HARNESS, "h", str(stub), sys.executable, str(log), root,
         "1" if local_only else "0", str(LIB)],
        env={"PATH": "/usr/bin:/bin", "ARGV_FILE": str(argv_file),
             "STUB_STDOUT": stdout, "STUB_RC": str(rc), "TMPDIR": str(tmp_path)},
        capture_output=True, text=True,
    )
    argv = argv_file.read_text().splitlines() if argv_file.exists() else []
    return proc.returncode, argv, log.read_text() if log.exists() else ""


OK = json.dumps({"success": True, "file_count": 1}, indent=2)
FAIL = json.dumps({"success": False, "error": "Folder not found: /x"}, indent=2)


def test_success_json_is_success(tmp_path):
    rc, argv, log = run(tmp_path, OK)
    assert rc == 0
    assert argv[:5] == ["index-local", "--path", str(tmp_path / "root"), "--name", "probe"]
    assert "mode: default" in log
    assert '"file_count": 1' in log  # streamed to the log


def test_success_false_with_exit_0_is_a_failure(tmp_path):
    # The real CLI does exactly this for a missing folder (verified 2026-10-23).
    rc, _, log = run(tmp_path, FAIL, rc=0)
    assert rc != 0
    assert "reported no success" in log


def test_no_json_at_all_is_a_failure(tmp_path):
    rc, _, _ = run(tmp_path, "Traceback: boom\n", rc=0)
    assert rc != 0


def test_nonzero_exit_propagates(tmp_path):
    rc, _, _ = run(tmp_path, "", rc=2)
    assert rc == 2


def test_stdout_chatter_before_json_is_tolerated(tmp_path):
    rc, _, _ = run(tmp_path, "provider says {hi}\nloading model\n" + OK)
    assert rc == 0


def test_default_repo_passes_no_posture_flags(tmp_path):
    _, argv, _ = run(tmp_path, OK)
    assert "--no-ai-summaries" not in argv
    assert "--embeddings" not in argv
    assert "--extra-ignore-pattern" not in argv


def test_local_only_repo_forces_posture_and_exclusions(tmp_path):
    rc, argv, log = run(tmp_path, OK, local_only=True)
    assert rc == 0
    assert "--no-ai-summaries" in argv
    assert argv[argv.index("--embeddings") + 1] == "off"
    pats = [argv[i + 1] for i, a in enumerate(argv) if a == "--extra-ignore-pattern"]
    # A pattern with a space must survive as one argument.
    assert pats == ["secret/a.md", "secret dir/b.md"]
    assert "mode: local-only" in log
    assert "forced exclusions: secret/a.md|secret dir/b.md" in log

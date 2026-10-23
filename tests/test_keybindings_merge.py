"""Alt+V image-paste binding: scripts/keybindings-merge.py and the refinery-doctor check.

Runs against a temp HOME, so the real ~/.claude/keybindings.json is never read or written.
"""

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "scripts" / "keybindings-merge.py"
DOCTOR = REPO_ROOT / "scripts" / "refinery-doctor.sh"


def env(home: Path) -> dict:
    return {**os.environ, "HOME": str(home)}


def run(home: Path, mode: str) -> str:
    r = subprocess.run(["python3", str(HELPER), mode], capture_output=True, text=True,
                       timeout=30, env=env(home))
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1]


def kb(home: Path) -> Path:
    return home / ".claude" / "keybindings.json"


def write(home: Path, data) -> None:
    kb(home).parent.mkdir(parents=True, exist_ok=True)
    kb(home).write_text(data if isinstance(data, str) else json.dumps(data))


def test_missing_file_is_created_with_the_binding(tmp_path):
    assert run(tmp_path, "check") == "missing"
    assert not kb(tmp_path).exists()  # check never writes
    assert run(tmp_path, "merge") == "merged"
    data = json.loads(kb(tmp_path).read_text())
    assert {"context": "Chat", "bindings": {"alt+v": "chat:imagePaste"}} in data["bindings"]
    assert run(tmp_path, "check") == "present"


def test_existing_bindings_are_kept(tmp_path):
    write(tmp_path, {"bindings": [
        {"context": "Chat", "bindings": {"ctrl+k": "chat:clear"}},
        {"context": "Global", "bindings": {"ctrl+t": "app:toggleTodos"}},
    ]})
    assert run(tmp_path, "merge") == "merged"
    data = json.loads(kb(tmp_path).read_text())
    assert data["bindings"][0]["bindings"] == {"ctrl+k": "chat:clear",
                                               "alt+v": "chat:imagePaste"}
    assert data["bindings"][1] == {"context": "Global",
                                   "bindings": {"ctrl+t": "app:toggleTodos"}}
    assert (kb(tmp_path).parent / "keybindings.json.bak").exists()


def test_alt_v_bound_elsewhere_is_left_alone(tmp_path):
    original = {"bindings": [{"context": "Chat", "bindings": {"alt+v": "chat:submit"}}]}
    write(tmp_path, original)
    assert run(tmp_path, "merge") == "taken"
    assert json.loads(kb(tmp_path).read_text()) == original


def test_invalid_json_is_never_written(tmp_path):
    write(tmp_path, "{not json")
    assert run(tmp_path, "merge") == "unreadable"
    assert kb(tmp_path).read_text() == "{not json"


def test_merge_is_idempotent(tmp_path):
    run(tmp_path, "merge")
    first = kb(tmp_path).read_text()
    assert run(tmp_path, "merge") == "present"
    assert kb(tmp_path).read_text() == first


def doctor(home: Path, *args):
    return subprocess.run(["bash", str(DOCTOR), "--check", "keybindings", *args],
                          capture_output=True, text=True, timeout=60, env=env(home))


def test_doctor_reports_then_fixes(tmp_path):
    r = doctor(tmp_path)
    assert r.returncode == 1 and "MIGRATION AVAILABLE" in r.stderr
    assert not kb(tmp_path).exists()
    r = doctor(tmp_path, "--fix")
    assert "FIXED" in r.stderr
    r = doctor(tmp_path)
    assert r.returncode == 0 and r.stdout.strip().endswith("DOCTOR: ok")

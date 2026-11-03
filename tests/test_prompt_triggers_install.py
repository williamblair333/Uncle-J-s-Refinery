"""features/prompt-triggers/install.sh: registers the triggers and the skill gate idempotently."""
import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "features" / "prompt-triggers" / "install.sh"


def run(home, *args):
    r = subprocess.run(["bash", str(INSTALL), *args], capture_output=True, text=True, timeout=30,
                       env={**os.environ, "HOME": str(home)})
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads((home / ".claude" / "settings.json").read_text())


def gates(cfg):
    return [h for e in cfg.get("hooks", {}).get("PreToolUse", []) for h in e["hooks"]
            if "prompt-triggers:skill-gate" in h["command"]]


def test_install_is_idempotent_and_uninstall_keeps_other_hooks(tmp_path):
    (tmp_path / ".claude").mkdir()
    other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "true  # other"}]}
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"PreToolUse": [other]}}))
    first = run(tmp_path)
    assert len(gates(first)) == 1
    gate_entry = [e for e in first["hooks"]["PreToolUse"] if gates({"hooks": {"PreToolUse": [e]}})]
    assert gate_entry[0]["matcher"] == "*"
    alt = [e for e in first["hooks"]["PreToolUse"]
           if any("prompt-triggers:alternatives-gate" in h["command"] for h in e["hooks"])]
    assert len(alt) == 1 and alt[0]["matcher"] == "Bash"
    assert run(tmp_path) == first
    after = run(tmp_path, "--uninstall")
    assert gates(after) == [] and after["hooks"]["PreToolUse"] == [other]
    assert "UserPromptSubmit" not in after["hooks"]

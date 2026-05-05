#!/usr/bin/env python3
"""
patch-jcodemunch-hook-paths.py

Rewrites every 'jcodemunch-mcp <subcommand>' hook entry in
~/.claude/settings.json to use the full path to the venv binary, so the
hooks actually fire instead of dying with "command not found".

Idempotent: safe to re-run. Backs up settings.json first.
"""
import json
import os
import shutil
import sys
from pathlib import Path

CLAUDE_DIR    = Path(os.path.expanduser(os.environ.get("CLAUDE_HOME", "~/.claude")))
SETTINGS_PATH = CLAUDE_DIR / "settings.json"
STACK_ROOT    = Path(__file__).resolve().parent

JCM_PATH = STACK_ROOT / ".venv" / "bin" / "jcodemunch-mcp"

if not SETTINGS_PATH.exists():
    sys.exit(f"ERROR: {SETTINGS_PATH} does not exist. Run install.sh first.")
if not JCM_PATH.exists():
    sys.exit(f"ERROR: {JCM_PATH} does not exist. Run install.sh to create the venv.")

# Backup
BACKUP = SETTINGS_PATH.with_suffix(".json.bak.jcm-path")
shutil.copy(str(SETTINGS_PATH), str(BACKUP))

d = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))

jcm_quoted = f"'{JCM_PATH.as_posix()}'"

changed = 0
for event_name, entries in d.get("hooks", {}).items():
    if not isinstance(entries, list):
        continue
    for matcher_obj in entries:
        for hook in matcher_obj.get("hooks", []):
            cmd = hook.get("command", "")
            if cmd.startswith("jcodemunch-mcp "):
                rest = cmd[len("jcodemunch-mcp "):]
                hook["command"] = f"{jcm_quoted} {rest}"
                changed += 1
            elif cmd == "jcodemunch-mcp":
                hook["command"] = jcm_quoted
                changed += 1

SETTINGS_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")

print(f"OK - patched {changed} hook command(s) to use full path")
print(f"  binary : {JCM_PATH}")
print(f"  backup : {BACKUP}")
if changed == 0:
    print("  (already using full paths or no jcodemunch-mcp hooks found)")

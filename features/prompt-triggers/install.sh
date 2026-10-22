#!/usr/bin/env bash
# prompt-triggers — install/uninstall
#
# Registers skill_name_trigger.py as a UserPromptSubmit hook in ~/.claude/settings.json,
# keyed on a marker so a re-run changes nothing. Written atomically after a backup,
# the same way features/product-quality/install.sh does it.
#
# Usage: install.sh [--uninstall]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS="${HOME}/.claude/settings.json"
MARKER="prompt-triggers:skill-name-trigger"
ACTION=install
[[ "${1:-}" == "--uninstall" ]] && ACTION=uninstall

chmod +x "$SCRIPT_DIR/skill_name_trigger.py"
python3 - "$SETTINGS" "$ACTION" "$SCRIPT_DIR" "$MARKER" <<'PYEOF'
import json, os, sys, tempfile, shutil

settings_path, action, script_dir, marker = sys.argv[1:5]
os.makedirs(os.path.dirname(settings_path), exist_ok=True)
try:
    with open(settings_path) as fh:
        config = json.load(fh)
except FileNotFoundError:
    config = {}
except json.JSONDecodeError as exc:
    print(f"    !!  settings.json is not valid JSON ({exc}) — refusing to touch it")
    raise SystemExit(1)

hooks = config.setdefault("hooks", {})
kept = [e for e in hooks.get("UserPromptSubmit", [])
        if not any(marker in h.get("command", "") for h in e.get("hooks", []))]
if action == "install":
    kept.append({"hooks": [{
        "type": "command",
        "command": f"[ -f {script_dir}/skill_name_trigger.py ] || exit 0; "
                   f"python3 {script_dir}/skill_name_trigger.py  # {marker}",
        "timeout": 5,
    }]})
if kept:
    hooks["UserPromptSubmit"] = kept
else:
    hooks.pop("UserPromptSubmit", None)
if not hooks:
    config.pop("hooks", None)

if os.path.exists(settings_path):
    shutil.copy2(settings_path, settings_path + ".bak")
with tempfile.NamedTemporaryFile("w", dir=os.path.dirname(settings_path), delete=False) as tmp:
    json.dump(config, tmp, indent=2)
    tmp.write("\n")
    tmp.flush()
    os.fsync(tmp.fileno())
    name = tmp.name
os.replace(name, settings_path)
print(f"    OK  skill-name trigger {action}ed in {settings_path}")
PYEOF

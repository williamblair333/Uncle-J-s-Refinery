#!/usr/bin/env bash
# prompt-triggers — install/uninstall
#
# Registers the UserPromptSubmit hooks in ~/.claude/settings.json, each keyed on a marker so
# a re-run changes nothing:
#   skill_name_trigger.py  Bill names a skill -> invoke it
#   meta_trigger.py        Bill asks why he had to catch something -> expert-bar + a real check
#   skill_router.py        Bill's prompt matches a judgment skill's triggers -> name it
# Written atomically after a backup, the same way features/product-quality/install.sh does it.
#
# Usage: install.sh [--uninstall]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS="${HOME}/.claude/settings.json"
ACTION=install
[[ "${1:-}" == "--uninstall" ]] && ACTION=uninstall

chmod +x "$SCRIPT_DIR/skill_name_trigger.py" "$SCRIPT_DIR/meta_trigger.py" "$SCRIPT_DIR/skill_router.py"
python3 - "$SETTINGS" "$ACTION" "$SCRIPT_DIR" <<'PYEOF'
import json, os, sys, tempfile, shutil

settings_path, action, script_dir = sys.argv[1:4]
TRIGGERS = [("skill_name_trigger.py", "prompt-triggers:skill-name-trigger"),
            ("meta_trigger.py", "prompt-triggers:meta-trigger"),
            ("skill_router.py", "prompt-triggers:skill-router")]
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
markers = [m for _, m in TRIGGERS]
kept = [e for e in hooks.get("UserPromptSubmit", [])
        if not any(m in h.get("command", "") for m in markers for h in e.get("hooks", []))]
if action == "install":
    for script, marker in TRIGGERS:
        kept.append({"hooks": [{
            "type": "command",
            "command": f"[ -f {script_dir}/{script} ] || exit 0; "
                       f"python3 {script_dir}/{script}  # {marker}",
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
print(f"    OK  prompt triggers ({len(TRIGGERS)}) {action}ed in {settings_path}")
PYEOF

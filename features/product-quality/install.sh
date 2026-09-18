#!/usr/bin/env bash
# product-quality — install/uninstall
#
# - Symlinks the product-quality skills into ~/.claude/skills/
# - Registers two hooks in ~/.claude/settings.json, keyed on markers so a
#   re-run changes nothing (idempotent)
# - Writes settings.json atomically, after a backup: two sessions installing at
#   once must not be able to truncate it
#
# Usage: install.sh [--uninstall]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLAUDE_SKILLS="${HOME}/.claude/skills"
SETTINGS="${HOME}/.claude/settings.json"
MARKER_SESSION="product-quality:product-md-check"
MARKER_PR="product-quality:pr-gate-guard"
SKILLS=(product-brief first-run-gate ux-heuristics product-focus-review)

step() { printf '==> %s\n' "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }

register_hooks() {
  local action=$1
  python3 - "$SETTINGS" "$action" "$SCRIPT_DIR" "$MARKER_SESSION" "$MARKER_PR" <<'PYEOF'
import json, os, sys, tempfile, shutil

settings_path, action, script_dir, marker_session, marker_pr = sys.argv[1:6]
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

def strip(event: str, marker: str) -> None:
    kept = []
    for entry in hooks.get(event, []):
        commands = [h.get("command", "") for h in entry.get("hooks", [])]
        if any(marker in c for c in commands):
            continue
        kept.append(entry)
    if kept:
        hooks[event] = kept
    else:
        hooks.pop(event, None)

strip("SessionStart", marker_session)
strip("PreToolUse", marker_pr)

if action == "install":
    hooks.setdefault("SessionStart", []).append({
        "hooks": [{
            "type": "command",
            "command": f"{script_dir}/hooks/product-md-check.sh  # {marker_session}",
        }],
    })
    hooks.setdefault("PreToolUse", []).append({
        "matcher": "Bash",
        "hooks": [{
            "type": "command",
            "command": f"{script_dir}/hooks/pr-gate-guard.sh  # {marker_pr}",
        }],
    })

if not hooks:
    config.pop("hooks", None)

# Back up, then write atomically: a concurrent install must not be able to
# leave a truncated settings.json behind.
if os.path.exists(settings_path):
    shutil.copy2(settings_path, settings_path + ".bak")

directory = os.path.dirname(settings_path)
with tempfile.NamedTemporaryFile("w", dir=directory, delete=False) as tmp:
    json.dump(config, tmp, indent=2)
    tmp.write("\n")
    tmp.flush()
    os.fsync(tmp.fileno())
    temp_name = tmp.name
os.replace(temp_name, settings_path)
print(f"    OK  hooks {action}ed in {settings_path}")
PYEOF
}

if [[ "${1:-}" == "--uninstall" ]]; then
  step "Removing product-quality skill symlinks"
  for name in "${SKILLS[@]}"; do
    link="$CLAUDE_SKILLS/$name"
    if [[ -L "$link" && "$(readlink "$link")" == "$PROJ_ROOT/global-skills/$name"* ]]; then
      rm "$link"; ok "removed $link"
    fi
  done
  step "Removing hooks"
  register_hooks uninstall
  step "Done. Gate reports in projects are left alone (delete .first-run-gate/ to clear)."
  exit 0
fi

step "Checking prerequisites"
python3 -c 'import yaml' 2>/dev/null && ok "python3 + pyyaml" || warn "pyyaml missing — the gate cannot parse PRODUCT.md (pip install pyyaml)"
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  ok "docker usable"
else
  warn "docker unavailable — the gate will report 'blocked' on this host (not a pass)"
fi

step "Linking skills"
mkdir -p "$CLAUDE_SKILLS"
for name in "${SKILLS[@]}"; do
  src="$PROJ_ROOT/global-skills/$name"
  link="$CLAUDE_SKILLS/$name"
  [[ -d "$src" ]] || { warn "$name missing from global-skills/ — skipped"; continue; }
  if [[ -L "$link" ]]; then
    ok "$name (already linked)"
  elif [[ -e "$link" ]]; then
    warn "$link exists and is not a symlink — left alone"
  else
    ln -s "$src" "$link"; ok "$name -> $link"
  fi
done

step "Registering hooks"
chmod +x "$SCRIPT_DIR"/hooks/*.sh "$SCRIPT_DIR"/first_run_gate.py "$SCRIPT_DIR"/retrofit.sh 2>/dev/null || true
register_hooks install

step "Installed."
printf '  Gate:     python3 %s/first_run_gate.py [PROJECT_DIR]\n' "$SCRIPT_DIR"
printf '  Retrofit: %s/retrofit.sh --help\n' "$SCRIPT_DIR"
printf '  Uninstall: %s/install.sh --uninstall\n' "$SCRIPT_DIR"

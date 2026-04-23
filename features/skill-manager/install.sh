#!/usr/bin/env bash
# features/skill-manager/install.sh
# New-machine setup for Uncle J's skill system.
#
# - Symlinks every skill in global-skills/ → ~/.claude/skills/<name>
# - Registers a SessionStart hook that symlinks project skills/ on entry
# - Registers a Stop hook that removes project skill symlinks on exit
#
# Usage:
#   bash features/skill-manager/install.sh [--uninstall]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SETTINGS="$PROJ_ROOT/.claude/settings.json"
CLAUDE_SKILLS="$HOME/.claude/skills"
GLOBAL_SKILLS="$PROJ_ROOT/global-skills"
PROJECT_SKILLS="$PROJ_ROOT/skills"
MARKER_SESSION="uncle-j-skill-manager-session"
MARKER_STOP="uncle-j-skill-manager-stop"

step() { printf '\n==> %s\n' "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }

source "$PROJ_ROOT/lib/feature-helpers.sh"

# ── helpers ──────────────────────────────────────────────────────────────────

_symlink_skills() {
  local src_dir=$1 label=$2
  local count=0
  for skill_dir in "$src_dir"/*/; do
    [[ -d "$skill_dir" ]] || continue
    local name
    name="$(basename "$skill_dir")"
    local link="$CLAUDE_SKILLS/$name"
    if [[ -L "$link" ]]; then
      ok "$label/$name (already linked)"
    else
      ln -s "$skill_dir" "$link"
      ok "$label/$name → $link"
    fi
    count=$((count + 1))
  done
  [[ $count -eq 0 ]] && ok "$label/ (empty — nothing to link)" || true
}

_remove_symlinks() {
  local src_dir=$1
  for skill_dir in "$src_dir"/*/; do
    [[ -d "$skill_dir" ]] || continue
    local name link
    name="$(basename "$skill_dir")"
    link="$CLAUDE_SKILLS/$name"
    if [[ -L "$link" ]] && [[ "$(readlink "$link")" == "$skill_dir"* ]]; then
      rm "$link"
      ok "Removed symlink: $link"
    fi
  done
}

_remove_hooks() {
  python3 - "$SETTINGS" "$MARKER_SESSION" "$MARKER_STOP" << 'PYEOF'
import sys, json
path, m1, m2 = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    cfg = json.load(f)
hooks = cfg.setdefault("hooks", {})
for event in ("SessionStart", "Stop"):
    groups = hooks.get(event, [])
    hooks[event] = [
        dict(g, hooks=[h for h in g.get("hooks", [])
                       if m1 not in h.get("command", "") and m2 not in h.get("command", "")])
        for g in groups
        if any(m1 not in h.get("command", "") and m2 not in h.get("command", "")
               for h in g.get("hooks", []))
    ]
    if not hooks[event]:
        del hooks[event]
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PYEOF
}

# ── uninstall ────────────────────────────────────────────────────────────────

if [[ "${1:-}" == "--uninstall" ]]; then
  step "Removing global-skill symlinks"
  _remove_symlinks "$GLOBAL_SKILLS"
  step "Removing project-skill symlinks"
  _remove_symlinks "$PROJECT_SKILLS"
  step "Removing hooks from $SETTINGS"
  _remove_hooks
  ok "Done"
  exit 0
fi

# ── install ──────────────────────────────────────────────────────────────────

step "Creating ~/.claude/skills if needed"
mkdir -p "$CLAUDE_SKILLS"
ok "$CLAUDE_SKILLS"

step "Symlinking global skills"
_symlink_skills "$GLOBAL_SKILLS" "global-skills"

step "Symlinking project skills"
_symlink_skills "$PROJECT_SKILLS" "skills"

step "Registering SessionStart + Stop hooks in $SETTINGS"
_remove_hooks  # idempotent

SESSION_CMD="bash $PROJ_ROOT/scripts/skill-link.sh link  # $MARKER_SESSION"
STOP_CMD="bash $PROJ_ROOT/scripts/skill-link.sh unlink  # $MARKER_STOP"

python3 - "$SETTINGS" "$SESSION_CMD" "$STOP_CMD" << 'PYEOF'
import sys, json
path, session_cmd, stop_cmd = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    cfg = json.load(f)
hooks = cfg.setdefault("hooks", {})
for event, cmd in [("SessionStart", session_cmd), ("Stop", stop_cmd)]:
    hooks.setdefault(event, []).append({
        "hooks": [{"type": "command", "command": cmd, "async": True}]
    })
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PYEOF
ok "Hooks registered"

step "Done"
printf '\n'
printf '  Global skills in:  %s/global-skills/\n' "$PROJ_ROOT"
printf '  Project skills in: %s/skills/\n' "$PROJ_ROOT"
printf '  Symlinked to:      %s\n' "$CLAUDE_SKILLS"
printf '\n'
printf '  To uninstall: bash %s/install.sh --uninstall\n' "$SCRIPT_DIR"
printf '\n'

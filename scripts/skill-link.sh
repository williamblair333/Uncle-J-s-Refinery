#!/usr/bin/env bash
# SessionStart / Stop hook: symlink or remove project-level skills.
# Usage: skill-link.sh link | unlink
set -euo pipefail
trap 'exit 0' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLAUDE_SKILLS="$HOME/.claude/skills"
mkdir -p "$CLAUDE_SKILLS"

link_skill_dirs() {
  local base_dir="$1"
  [[ -d "$base_dir" ]] || return 0
  for skill_dir in "$base_dir"/*/; do
    [[ -d "$skill_dir" ]] || continue
    local name link target
    name="$(basename "$skill_dir")"
    link="$CLAUDE_SKILLS/$name"
    target="$(readlink -f "$skill_dir")"
    case "${2:-}" in
      link)
        if [[ -L "$link" ]] && [[ "$(readlink -f "$link")" == "$target" ]]; then
          true  # already correctly linked
        else
          rm -rf "$link"
          ln -sfn "$skill_dir" "$link"
        fi
        ;;
      unlink)
        [[ -L "$link" ]] && [[ "$(readlink "$link")" == "$skill_dir"* ]] && rm "$link" || true
        ;;
    esac
  done
}

link_skill_dirs "$PROJ_ROOT/skills"        "${1:-}"
# Global skills are permanent (managed by install-reliability.sh) — link only, never unlink
[[ "${1:-}" == "link" ]] && link_skill_dirs "$PROJ_ROOT/global-skills" "link"

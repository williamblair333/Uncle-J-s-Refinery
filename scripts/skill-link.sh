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

# ~/.agents/skills is the cross-harness skill dir (Codex, Gemini CLI, Copilot CLI).
# Other tools install into it, so a real directory there is never replaced or deleted:
# only our own symlinks are created, repointed, or pruned when dangling.
link_agents_skills() {
  local base_dir="$1" agents_skills="$HOME/.agents/skills"
  [[ -d "$base_dir" ]] || return 0
  mkdir -p "$agents_skills"
  for skill_dir in "$base_dir"/*/; do
    [[ -d "$skill_dir" ]] || continue
    local link="$agents_skills/$(basename "$skill_dir")"
    if [[ -L "$link" && "$(readlink "$link")" == "$base_dir"/* ]]; then
      [[ "$(readlink -f "$link")" == "$(readlink -f "$skill_dir")" ]] || ln -sfn "$skill_dir" "$link"
    elif [[ -L "$link" || -e "$link" ]]; then
      echo "skill-link: $link is not our symlink; left alone" >&2
    else
      ln -s "$skill_dir" "$link"
    fi
  done
  for link in "$agents_skills"/*; do
    if [[ -L "$link" && ! -e "$link" && "$(readlink "$link")" == "$base_dir"/* ]]; then
      rm -f "$link"
    fi
  done
  return 0
}

link_skill_dirs "$PROJ_ROOT/skills"        "${1:-}"
# Global skills are permanent (managed by install-reliability.sh) — link only, never unlink
if [[ "${1:-}" == "link" ]]; then
  link_skill_dirs "$PROJ_ROOT/global-skills" "link"
  link_agents_skills "$PROJ_ROOT/global-skills"
fi

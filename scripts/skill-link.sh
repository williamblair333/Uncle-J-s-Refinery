#!/usr/bin/env bash
# SessionStart / Stop hook: symlink or remove project-level skills.
# Usage: skill-link.sh link | unlink
set -euo pipefail
trap 'exit 0' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_SKILLS="$PROJ_ROOT/skills"
CLAUDE_SKILLS="$HOME/.claude/skills"

[[ -d "$PROJECT_SKILLS" ]] || exit 0

for skill_dir in "$PROJECT_SKILLS"/*/; do
  [[ -d "$skill_dir" ]] || continue
  name="$(basename "$skill_dir")"
  link="$CLAUDE_SKILLS/$name"
  case "${1:-}" in
    link)
      [[ -e "$link" ]] || ln -s "$skill_dir" "$link"
      ;;
    unlink)
      [[ -L "$link" ]] && [[ "$(readlink "$link")" == "$skill_dir"* ]] && rm "$link" || true
      ;;
  esac
done

#!/usr/bin/env bash
# Stop hook — warns when current branch has unpushed commits.
# Non-blocking: outputs systemMessage only; never delays or blocks session exit.
set -uo pipefail

# Find repo root; exit cleanly if not in a git repo
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0

# Check if upstream tracking branch is set; exit cleanly if not
UPSTREAM=$(git -C "$REPO_ROOT" rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null) || exit 0

# Count unpushed commits — timeout 5s so hook never blocks session exit
COUNT=$(timeout 5 git -C "$REPO_ROOT" log "@{u}..HEAD" --oneline 2>/dev/null | wc -l | tr -d ' ') || exit 0

[[ "${COUNT:-0}" -gt 0 ]] || exit 0

BRANCH=$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || echo "unknown")

jq -n --argjson count "$COUNT" --arg branch "$BRANCH" --arg upstream "$UPSTREAM" \
  '{"systemMessage": ("⚠ " + ($count|tostring) + " unpushed commit(s) on " + $branch + " → " + $upstream + "\n  git push")}'

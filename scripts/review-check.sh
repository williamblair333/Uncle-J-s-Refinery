#!/usr/bin/env bash
# SessionStart hook: check _review/ items, auto-move resolved ones to _reviewed/.
# Outputs JSON systemMessage listing pending items.
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REVIEW_DIR="$PROJ_ROOT/_review"
REVIEWED_DIR="$PROJ_ROOT/_reviewed"

pending=()
moved=()

for f in "$REVIEW_DIR"/*.md; do
  [[ -f "$f" ]] || continue
  filename="$(basename "$f")"

  status=$(grep -m1 '^status:' "$f" 2>/dev/null | sed 's/status: *//' | tr -d '"' || echo "pending")
  issue_url=$(grep -m1 '^issue_url:' "$f" 2>/dev/null | sed 's/issue_url: *//' | tr -d '"' || echo "")
  title=$(grep -m1 '^title:' "$f" 2>/dev/null | sed 's/title: *//' | tr -d '"' || echo "$filename")

  # If filed and gh available, check if closed upstream
  if [[ "$status" == "filed" && -n "$issue_url" ]] && command -v gh &>/dev/null; then
    issue_state=$(gh issue view "$issue_url" --json state -q '.state' 2>/dev/null || echo "")
    if [[ "$issue_state" == "CLOSED" ]]; then
      # Update status in file
      sed -i 's/^status: filed/status: resolved/' "$f"
      mv "$f" "$REVIEWED_DIR/$filename"
      moved+=("$title")
      continue
    fi
  fi

  pending+=("[$status] $title")
done

# Build systemMessage
msg=""
if [[ ${#moved[@]} -gt 0 ]]; then
  msg+="✓ Moved to _reviewed: "
  for m in "${moved[@]}"; do msg+="$m | "; done
  msg="${msg% | }"$'\n'
fi

if [[ ${#pending[@]} -gt 0 ]]; then
  msg+="_review/ has ${#pending[@]} pending item(s):"$'\n'
  for p in "${pending[@]}"; do msg+="  • $p"$'\n'; done
  msg+="Update issue_url + set status: filed once submitted, or status: resolved to move to _reviewed."
fi

if [[ -n "$msg" ]]; then
  python3 -c "import json,sys; print(json.dumps({'systemMessage': sys.argv[1]}))" "$msg"
fi

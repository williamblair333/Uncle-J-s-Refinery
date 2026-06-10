#!/usr/bin/env bash
# features/gemini-integration/startup-probe.sh
# Read-only context synchronization for Gemini CLI.
# Synthesizes recent repo changes, config drift, and AI playbooks.

set -uo pipefail

# Find repo root
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

printf "\n--- [ RECENT CHANGES ] ---\n"
git -C "$REPO_ROOT" log -n 5 --oneline || echo "Git history unavailable."

printf "\n--- [ CONFIG DRIFT CHECK ] ---\n"
if [[ -f "$REPO_ROOT/scripts/refinery-doctor.sh" ]]; then
    bash "$REPO_ROOT/scripts/refinery-doctor.sh" || true
else
    echo "refinery-doctor.sh not found."
fi

printf "\n--- [ LATEST DREAMING PLAYBOOKS ] ---\n"
DREAM_DIR="$HOME/.claude/dreaming-output"
if [[ -d "$DREAM_DIR" ]]; then
    LATEST_DREAM=$(ls -t "$DREAM_DIR"/dream-*.md 2>/dev/null | head -n 1)
    if [[ -n "$LATEST_DREAM" ]]; then
        printf "Source: %s\n\n" "$LATEST_DREAM"
        # Extract the "Proven Playbooks" section
        python3 - "$LATEST_DREAM" <<'PYEOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
content = p.read_text()
if "## Proven Playbooks" in content:
    print(content[content.index("## Proven Playbooks"):].strip())
else:
    print("No 'Proven Playbooks' found in latest dream.")
PYEOF
    else
        echo "No dreaming output found."
    fi
else
    echo "Dreaming output directory not found."
fi

printf "\n--- [ REFINERY HEALTH SUMMARY ] ---\n"
if [[ -f "$REPO_ROOT/healthcheck.sh" ]]; then
    bash "$REPO_ROOT/healthcheck.sh" --quick 2>&1 | tail -n 1 || true
fi

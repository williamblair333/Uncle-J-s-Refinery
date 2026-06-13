#!/usr/bin/env bash
# features/gemini-integration/install.sh
# Installs (or removes) the Gemini CLI "Passive Observer" mandates in GEMINI.md.
# Usage: ./install.sh [--uninstall]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GEMINI_MD="$REPO_ROOT/GEMINI.md"
MARKER_START="<!-- UNCLE-J-GEMINI-START -->"
MARKER_END="<!-- UNCLE-J-GEMINI-END -->"

step() { printf '\n==> %s\n' "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }

# ---------------------------------------------------------------------------
# --uninstall
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--uninstall" ]]; then
    step "Removing Gemini mandates from $GEMINI_MD"
    if [[ -f "$GEMINI_MD" ]]; then
        sed -i "/$MARKER_START/,/$MARKER_END/d" "$GEMINI_MD"
        ok "Mandates removed."
    else
        ok "GEMINI.md not found, nothing to do."
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------
step "Checking dependencies"
for dep in python3 bash git; do
    if command -v "$dep" &>/dev/null; then
        ok "$dep found"
    else
        warn "$dep not found — please install it and retry"
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# Mandate Injection
# ---------------------------------------------------------------------------
step "Injecting Gemini mandates into $GEMINI_MD"

# Ensure startup-probe is executable
chmod +x "$SCRIPT_DIR/startup-probe.sh"

MANDATES=$(cat <<EOF
$MARKER_START
## Uncle J's Refinery Integration (Passive Observer)

**Mandate:** You are operating in a workspace managed by Uncle J's Refinery. To maintain functional parity with Claude Code while ensuring zero operational interference, you MUST adhere to the following rules:

1.  **Passive Observation**: NEVER modify \`~/.claude/settings.json\` or the Refinery's internal \`state/\` files. Your integration is strictly read-only regarding Claude's state.
2.  **Structural Exploration**: Use the Refinery's retrieval stack instead of your standard \`grep_search\` or \`read_file\` tools.
    - **Code**: Use \`$REPO_ROOT/.venv/bin/jcodemunch-mcp\` via \`run_shell_command\`.
    - **Memory**: Use \`$REPO_ROOT/.venv-memweave/bin/python $REPO_ROOT/scripts/memweave/mw_search.py "query" --k 5\` via \`run_shell_command\` before proposing architectural changes.
3.  **Context Synchronization**: At the start of any complex task (research, refactoring, or bug fixing), run the startup probe to synchronize with the latest repository changes and AI playbooks:
    - \`bash $REPO_ROOT/features/gemini-integration/startup-probe.sh\`
4.  **Research First**: Before proposing a new solution or starting a substantive task, you MUST search the internet (via search tools) to ensure a solution does not already exist and to stay current with the latest technical standards and library updates. Do NOT reinvent the wheel.
5.  **Output Discipline**: Adopt the \`jOutputMunch\` format. Provide high-signal technical responses. Eliminate conversational filler, preambles, and summaries unless specifically requested.
6.  **Auto-Skill**: You are equipped with the \`gemini-auto-skill\`. You MUST monitor your sessions for reusable workflows and draft native Gemini skills into \`.gemini/skills/\` when you identify a repeatable pattern that would benefit from automation.
7.  **Validation**: Before concluding any task, verify your changes by running:
    - \`bash $REPO_ROOT/healthcheck.sh --quick\`
$MARKER_END
EOF
)

# Idempotent injection
if [[ -f "$GEMINI_MD" ]]; then
    # Remove existing block if present
    sed -i "/$MARKER_START/,/$MARKER_END/d" "$GEMINI_MD"
    # Append to end
    printf "\n%s\n" "$MANDATES" >> "$GEMINI_MD"
else
    # Create new file
    printf "%s\n" "$MANDATES" > "$GEMINI_MD"
fi

ok "Mandates injected into GEMINI.md"
printf "\n    Gemini CLI will now automatically detect and follow the Refinery's\n"
printf "    retrieval-first methodology when operating in this repository.\n\n"

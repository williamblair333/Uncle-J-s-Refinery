#!/usr/bin/env bash
# lib/install-update.sh — section-detection helpers for install.sh --update.
# Sourced by install.sh; functions here must not depend on install.sh globals.

# detect_changed_sections CHANGED_FILES_STRING
#
# Reads newline-separated changed file paths from $1.
# Prints section names (one per line) that need to run.
#
# Section names:
#   uv_sync       pyproject.toml or uv.lock changed
#   skills        global-skills/, global-agents/, or install-reliability.sh changed
#   mcp_templates mcp-clients/ template changed
#   jdocmunch     any .md file changed
#   full          install.sh itself changed (caller should run full install)
detect_changed_sections() {
    local changed="$1"
    local -a sections=()
    echo "$changed" | grep -qE '^(pyproject\.toml|uv\.lock)$'                            && sections+=("uv_sync")
    echo "$changed" | grep -qE '^(global-skills/|global-agents/|install-reliability\.sh$)' && sections+=("skills")
    echo "$changed" | grep -qE '^mcp-clients/'                                             && sections+=("mcp_templates")
    echo "$changed" | grep -qE '\.md$'                                                     && sections+=("jdocmunch")
    echo "$changed" | grep -qE '^install\.sh$'                                             && sections+=("full")
    printf '%s\n' "${sections[@]}"
}

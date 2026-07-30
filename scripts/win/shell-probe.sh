#!/usr/bin/env bash
# SessionStart diagnostic: record which shell and toolchain the hook runner
# actually gives us on this host.
#
# Why this exists: the Windows port assumes Claude Code executes `command` hooks
# through Git Bash (the existing hooks are written in bash and use `[[ ]]`). That
# assumption was not verifiable without running a real session. This probe proves
# or disproves it — read state/win-port-probe.log after your next session start.
#
# Safe to delete once the log confirms the environment.
LOG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/state"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG="$LOG_DIR/win-port-probe.log"

{
    printf -- '--- hook shell probe %s ---\n' "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null)"
    if [ -n "${BASH_VERSION:-}" ]; then
        printf 'interpreter : bash %s\n' "$BASH_VERSION"
    else
        printf 'interpreter : NOT BASH (hook runner is not Git Bash)\n'
    fi
    printf 'uname       : %s\n' "$(uname -s 2>/dev/null || echo n/a)"
    printf 'pwd         : %s\n' "$(pwd 2>/dev/null)"
    printf 'MSYS        : %s\n' "${MSYS:-unset}"
    for c in python3 uv jq flock git; do
        printf '%-11s : %s\n' "$c" "$(command -v "$c" 2>/dev/null || echo MISSING)"
    done
} >>"$LOG" 2>&1

exit 0

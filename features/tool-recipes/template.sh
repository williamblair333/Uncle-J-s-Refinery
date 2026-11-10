#!/usr/bin/env bash
# my-tool.sh - one line saying what this fixes or does
#
# Symptom this solves:
#   What the user sees when it's broken.
#
# Cause:
#   Why it happens.
#
# Fix:
#   What this script changes, and why that cures it.
#
# Full write-up: my-tool.md
#
# Copy this to your project, rename it, fill in check_state and apply_fix,
# add a test (tests/test_my_tool.py, or a --test mode), and give it a recipe:
#
#   # one line saying what it does (--check, --fix, --dry-run)
#   [group('tools')]
#   my-tool *args:
#       ./my-tool.sh {{args}}
#
# Standard: docs/TOOLS-STANDARD.md in Uncle-J-s-Refinery. Check with: just -g tools lint .

set -euo pipefail

VERSION="1.0.0"
PROG="$(basename "$0")"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # files next to the script
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/${PROG%.sh}"

MODE="check"
DRY_RUN=false
JSON=false

usage() {
    cat <<EOF
$PROG $VERSION - one line saying what this fixes or does

Usage: $PROG [--check | --fix] [--dry-run] [--json]

  -c, --check     report whether the problem is present; change nothing (default)
  -f, --fix       fix it (safe to run again)
  -n, --dry-run   with --fix: print what would change, change nothing
      --json      print the result as JSON
  -h, --help      this help
  -V, --version   print the version

Exit: 0 ok, 1 problem found (--check) or fix failed, 2 usage or environment error.
EOF
}

die() { printf '%s: %s\n' "$PROG" "$1" >&2; exit "${2:-2}"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        -c|--check)   MODE="check"; shift ;;
        -f|--fix)     MODE="fix"; shift ;;
        -n|--dry-run) DRY_RUN=true; shift ;;
        --json)       JSON=true; shift ;;
        -h|--help)    usage; exit 0 ;;
        -V|--version) echo "$PROG $VERSION"; exit 0 ;;
        *)            die "unknown option: $1 (see --help)" ;;
    esac
done

report() {  # report <ok|problem|fixed|would-fix> <message>
    if $JSON; then
        printf '{"status":"%s","message":"%s"}\n' "$1" "$2"
    else
        printf '[%s] %s\n' "$1" "$2"
    fi
}

check_state() {
    # Return 0 when everything is fine, 1 when the problem is present.
    # Read only. Example: grep -q 'serial=' /etc/cups/printers.conf && return 1
    [[ -d "$HERE" ]]
}

apply_fix() {
    # Make the change. It must be safe to run twice.
    mkdir -p "$STATE_DIR"
}

if [[ "$MODE" == "check" ]]; then
    if check_state; then report ok "nothing to fix"; exit 0; fi
    report problem "the problem is present; run with --fix"; exit 1
fi

if check_state; then report ok "already fixed"; exit 0; fi
if $DRY_RUN; then report would-fix "would create $STATE_DIR"; exit 0; fi
apply_fix
if check_state; then report fixed "fixed"; exit 0; fi
report problem "fix ran but the check still fails"; exit 1

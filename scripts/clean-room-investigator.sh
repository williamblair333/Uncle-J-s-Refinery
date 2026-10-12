#!/usr/bin/env bash
# clean-room-investigator.sh — start Claude Code as the clean-room Investigator.
#
# The Investigator runs under its own Claude profile (CLAUDE_CONFIG_DIR), so
# REA's registration and skill, its session transcripts, settings, hooks and
# login stay out of the default profile the Implementer uses. The working
# directory must carry the .clean-room-investigator marker, which also keeps
# these sessions out of the memweave store (scripts/memweave/export_transcripts.py).
#
# Usage, from the investigator workspace:
#   scripts/clean-room-investigator.sh --init    # once: create the marker here
#   scripts/clean-room-investigator.sh [claude args...]
#
# CLEAN_ROOM_CONFIG_DIR overrides the profile location (default ~/.claude-investigator).
# The profile needs its own login on first use. See global-skills/clean-room-rebuild.
set -euo pipefail

MARKER=".clean-room-investigator"
PROFILE="${CLEAN_ROOM_CONFIG_DIR:-$HOME/.claude-investigator}"

if [ "${1:-}" = "--init" ]; then
    : > "$MARKER"
    printf 'Marked %s as a clean-room investigator workspace.\n' "$PWD"
    exit 0
fi

dir="$PWD"
while [ "$dir" != "/" ] && [ ! -e "$dir/$MARKER" ]; do
    dir="$(dirname "$dir")"
done
if [ ! -e "$dir/$MARKER" ]; then
    printf 'clean-room-investigator: no %s in %s or any parent.\n' "$MARKER" "$PWD" >&2
    printf 'Run this from the investigator workspace, or mark it first with --init.\n' >&2
    exit 1
fi

mkdir -p "$PROFILE"
export CLAUDE_CONFIG_DIR="$PROFILE"
exec claude "$@"

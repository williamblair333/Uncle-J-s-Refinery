#!/usr/bin/env bash
# session-start.sh - SessionStart hook: show this project's inbox notes, keep `just -g` current
#
# 1. Prints unread notes in <project>/inbox/ (scripts/inbox.py notice). Silent when none.
# 2. If any project's justfile is newer than the global justfile, rewrites it in the
#    background (scripts/tools.py sync), so `just -g <project> <recipe>` sees new
#    projects and recipes, and a project whose justfile broke drops out instead of
#    breaking every `just -g` call. Log: state/tools-sync.log.
#
# Never fails the session: every error is swallowed and the hook exits 0.
# Installed by features/tool-recipes/install.sh.

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"
PROJ_ROOT="${PROJ_ROOT:-/opt/proj}"
GLOBAL="${GLOBAL_JUSTFILE:-${XDG_CONFIG_HOME:-$HOME/.config}/just/justfile}"

payload=""
[[ -t 0 ]] || payload="$(timeout 5 cat 2>/dev/null || true)"   # never wait on a terminal
printf '%s' "$payload" | python3 "$REPO_ROOT/scripts/inbox.py" notice 2>/dev/null || true

command -v just >/dev/null 2>&1 || exit 0
stale=false
if [[ ! -f "$GLOBAL" ]]; then
    stale=true
elif [[ -n "$(find "$PROJ_ROOT" -mindepth 2 -maxdepth 2 \( -name justfile -o -name Justfile -o -name .justfile \) -newer "$GLOBAL" -print -quit 2>/dev/null)" ]]; then
    stale=true
elif [[ -n "$(find "$PROJ_ROOT" -mindepth 0 -maxdepth 1 -type d -newer "$GLOBAL" -print -quit 2>/dev/null)" ]]; then
    stale=true   # a project folder was added or removed (that changes PROJ_ROOT's own mtime)
fi
if $stale; then
    mkdir -p "$REPO_ROOT/state" 2>/dev/null
    ( { date -Is; python3 "$REPO_ROOT/scripts/tools.py" sync; } >>"$REPO_ROOT/state/tools-sync.log" 2>&1 & ) 2>/dev/null
fi
exit 0

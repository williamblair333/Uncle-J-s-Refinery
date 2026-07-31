#!/usr/bin/env bash
# Make a Windows venv answer to the POSIX layout the rest of this repo assumes.
#
# ~20 call sites across install.sh, healthcheck.sh and scripts/ hardcode
# "$ROOT/.venv/bin/<tool>". A Windows venv puts everything in .venv/Scripts and
# ships no bare `python3`. Rather than rewrite every call site, this recreates the
# two things they expect:
#
#   .venv/bin           -> symlink to .venv/Scripts   (MSYS appends .exe on exec,
#                          so .venv/bin/jcodemunch-mcp resolves to the .exe)
#   .venv/Scripts/python3.exe -> copy of python.exe    (POSIX venvs expose python3)
#
# .venv/ is gitignored, so both are lost whenever the venv is rebuilt
# (`uv sync`, `uv venv`). This script is therefore idempotent and is invoked from
# scripts/win/hook.sh on every SessionStart to self-heal.
#
# Requires native symlinks: MSYS=winsymlinks:nativestrict plus Windows Developer
# Mode (or an elevated shell). Falls back to a directory copy warning if unavailable.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

export MSYS="${MSYS:-winsymlinks:nativestrict}"

# Both venvs need the shim: .venv is referenced as .venv/bin/<tool> across the
# repo, and .venv-memweave as .venv-memweave/bin/python by install.sh and the
# memweave Stop hook.
for name in .venv .venv-memweave; do
    VENV="$ROOT/$name"
    [ -d "$VENV/Scripts" ] || continue   # absent, or not a Windows venv

    # 1. <venv>/bin -> Scripts
    if [ ! -e "$VENV/bin" ]; then
        if ln -sfn "$VENV/Scripts" "$VENV/bin" 2>/dev/null && [ -L "$VENV/bin" ]; then
            printf '    AUTO-FIXED  %s/bin -> Scripts (POSIX layout shim)\n' "$name"
        else
            printf '    WARN        could not create %s/bin symlink; enable Windows\n' "$name"
            printf '                Developer Mode so scripts using %s/bin/... resolve\n' "$name"
            rm -rf "$VENV/bin" 2>/dev/null || true
        fi
    fi

    # 2. python3.exe alongside python.exe
    if [ ! -e "$VENV/Scripts/python3.exe" ] && [ -e "$VENV/Scripts/python.exe" ]; then
        if cp "$VENV/Scripts/python.exe" "$VENV/Scripts/python3.exe" 2>/dev/null; then
            printf '    AUTO-FIXED  %s/Scripts/python3.exe (POSIX python3 shim)\n' "$name"
        fi
    fi
done

exit 0

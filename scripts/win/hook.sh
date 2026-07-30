#!/usr/bin/env bash
# Single entry point for every hook invocation on Windows.
#
# Why a dispatcher instead of inline hook commands:
#   1. `bash` is not on the Windows PATH (only Git\cmd is), so settings.json must
#      name the interpreter by absolute path. Doing that once, here, keeps the
#      JSON free of per-hook quoting.
#   2. Several original hooks relied on shell redirection (`>> log 2>&1`,
#      `2>/dev/null || true`). Invoking a script directly from settings.json
#      would drop those, because there is no shell to interpret them. They are
#      preserved below instead.
#   3. Paths are derived from this file's location, so nothing hardcodes a drive
#      letter and the same dispatcher works if the repo moves.
#
# Usage: hook.sh <action> [arg]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "$ROOT/state" 2>/dev/null

# Hooks inherit Claude Code's environment, which does not necessarily carry the
# user PATH — the SessionStart probe recorded uv, uvx and jq as MISSING even
# though all three are installed. Every one of them is called by a hook or by a
# script a hook invokes, and each failure is swallowed (`2>/dev/null || true`),
# so an absent binary reports success instead of erroring. Put the known install
# locations on PATH here rather than relying on the ambient value.
for _d in "$ROOT/.venv/Scripts" /c/util/apps/jq /c/util/apps/uv; do
    [ -d "$_d" ] && case ":$PATH:" in *":$_d:"*) ;; *) PATH="$_d:$PATH" ;; esac
done
export PATH
unset _d

case "${1:-}" in
    # --- PostToolUse -------------------------------------------------------
    checkpoint)
        exec bash "$ROOT/scripts/win/checkpoint.sh"
        ;;
    # --- PreToolUse --------------------------------------------------------
    commit-guard)
        exec bash "$ROOT/scripts/win/commit-doc-guard.sh"
        ;;
    mcp-log)
        exec bash "$ROOT/scripts/win/mcp-log.sh"
        ;;
    # The discipline guards run from the repo copies rather than the
    # ~/.claude/hooks/discipline/ copies install-reliability.sh makes: that
    # script wires them with jq, which was absent, so the wiring silently
    # warned-and-continued and the guards were never registered on this host.
    grep-guard)
        exec bash "$ROOT/hooks/discipline/grep-guard.sh"
        ;;
    edit-surface-guard)
        exec bash "$ROOT/hooks/discipline/edit-surface-guard.sh"
        ;;
    unpushed-warn)
        exec bash "$ROOT/hooks/discipline/unpushed-warn.sh"
        ;;
    # --- SessionStart ------------------------------------------------------
    probe)
        exec bash "$ROOT/scripts/win/shell-probe.sh"
        ;;
    review-check)
        bash "$ROOT/scripts/review-check.sh" 2>/dev/null || true
        ;;
    autofix)
        # Re-assert the POSIX venv shims first: .venv/ is gitignored, so a rebuild
        # (uv sync) silently removes them and every .venv/bin/... call site breaks.
        bash "$ROOT/scripts/win/venv-compat.sh" || true
        bash "$ROOT/scripts/session-start-autofix.sh" || true
        ;;
    # --- Stop --------------------------------------------------------------
    session-notify)
        bash "$ROOT/scripts/session-notify.sh" || true
        ;;
    skill-suggest)
        bash "$ROOT/scripts/skill-suggest.sh" || true
        ;;
    memweave-sync)
        bash "$ROOT/scripts/memweave/sync_memory.sh" '' 15 \
            >>"$ROOT/state/memweave-sync.log" 2>&1 || true
        ;;
    # --- SessionStart + Stop (takes link|unlink) ---------------------------
    skill-link)
        bash "$ROOT/scripts/skill-link.sh" "${2:-}" || true
        ;;
    *)
        # Unknown action: never fail a session over it.
        exit 0
        ;;
esac

exit 0

#!/usr/bin/env bash
# Single entry point for every scheduled job on Windows.
#
# Mirrors scripts/win/hook.sh, for the same reasons: bash is not on the Windows
# PATH so the registered command must name the interpreter absolutely; Task
# Scheduler has no shell, so the `>> log 2>&1` redirections the cron entries
# carried are preserved here instead; and PATH is asserted in one place because
# these jobs run outside any Claude Code session, where even less of the user
# environment is present than a hook sees.
#
# Usage: run-job.sh <job>
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "$ROOT/state" 2>/dev/null

for _d in "$ROOT/.venv/Scripts" /c/util/apps/jq /c/util/apps/uv; do
    [ -d "$_d" ] && case ":$PATH:" in *":$_d:"*) ;; *) PATH="$_d:$PATH" ;; esac
done
export PATH
unset _d

# auto-maintain shells out to the Claude CLI; the Linux cron entry passes
# CLAUDE_BIN explicitly for the same reason.
[ -z "${CLAUDE_BIN:-}" ] && [ -x "$HOME/.local/bin/claude.exe" ] \
    && export CLAUDE_BIN="$HOME/.local/bin/claude.exe"

# Every job below resolves its binaries through .venv/bin, which is a compat
# symlink that any `uv sync` destroys — including the one auto-maintain itself
# runs at 03:00. Re-assert before the job, so a reindex the following night does
# not fail on a shim that auto-maintain removed and no session was open to
# restore. Same call the SessionStart autofix hook makes.
bash "$ROOT/scripts/win/venv-compat.sh" >/dev/null 2>&1 || true

# jcodemunch-reindex, jdocmunch-reindex and auto-maintain already `tee` every
# line into their own state/*.log. Redirecting them into the same file writes
# each line twice, so their output goes to a runner log instead — which still
# captures anything they emit outside log(), such as a stack trace.
RUNNER_LOG="$ROOT/state/run-job.log"

case "${1:-}" in
    jcodemunch-reindex)
        bash "$ROOT/scripts/jcodemunch-reindex.sh" >>"$RUNNER_LOG" 2>&1
        ;;
    jdocmunch-reindex)
        bash "$ROOT/scripts/jdocmunch-reindex.sh" >>"$RUNNER_LOG" 2>&1
        ;;
    auto-maintain)
        bash "$ROOT/scripts/auto-maintain.sh" >>"$RUNNER_LOG" 2>&1
        # auto-maintain runs `uv sync --inexact`, which removes .venv/bin. Put it
        # back immediately rather than leaving the stack broken until a human
        # opens a session.
        bash "$ROOT/scripts/win/venv-compat.sh" >>"$RUNNER_LOG" 2>&1 || true
        ;;
    memweave-sync)
        # No self-logging here — this one owns its log file.
        bash "$ROOT/scripts/memweave/sync_memory.sh" --all \
            >>"$ROOT/state/memweave-sync.log" 2>&1
        ;;
    *)
        echo "run-job.sh: unknown job '${1:-}'" >&2
        exit 2
        ;;
esac

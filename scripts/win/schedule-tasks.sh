#!/usr/bin/env bash
# Register the Uncle J maintenance jobs with Windows Task Scheduler.
#
# Windows has no cron daemon, so install.sh section 5c registers nothing here and
# the jobs it schedules on Linux simply never run. That is not cosmetic: without
# them nothing reindexes jcodemunch/jdocmunch, syncs memweave, or upgrades the
# stack in the background. The SessionStart autofix hook covers reindexing only
# when a session happens to start, and the Stop hook syncs memweave only when a
# session ends cleanly.
#
# Task names match the cron labels exactly so healthcheck.sh can probe either
# scheduler with one accessor (see scheduled_jobs() there).
#
# The registration itself lives in schedule-tasks.ps1 — Task Scheduler's
# StartWhenAvailable setting has no schtasks.exe flag, and without it a job
# scheduled at 01:00 on a machine that is asleep is skipped rather than deferred.
#
# Usage: schedule-tasks.sh [--remove]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PS1_WIN="$(cygpath -w "$ROOT/scripts/win/schedule-tasks.ps1" 2>/dev/null)" || PS1_WIN=""
[ -n "$PS1_WIN" ] || { echo "could not resolve schedule-tasks.ps1" >&2; exit 1; }

command -v powershell.exe >/dev/null 2>&1 || {
    echo "powershell.exe not found — this script only applies to Windows hosts" >&2
    exit 1
}

if [ "${1:-}" = "--remove" ]; then
    exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PS1_WIN" -Remove
fi
exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PS1_WIN"

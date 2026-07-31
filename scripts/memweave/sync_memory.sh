#!/usr/bin/env bash
# sync_memory.sh — export Claude transcripts to markdown and index them into the
# memweave memory store. This is the single seam the future freshness cron and the
# Stop-hook will both call.
#
# Idempotent: export overwrites each per-session markdown file; memweave's index()
# re-embeds only changed files (SHA-256 hash compare), so re-running is cheap and
# resumes a partial load.
#
# flock -n guards the single-writer sqlite index against concurrent runs (cron +
# Stop-hook firing together) — without it, two index() passes would race and could
# corrupt the store.
#
# Logging: writes progress to stdout and errors to stderr. Each caller owns its log
# destination — the nightly cron and the Stop-hook both redirect to
# state/memweave-sync.log; a manual run prints to the terminal. (Not self-teeing
# avoids double-logged lines when a caller also redirects to that file.)
#
# Usage:
#   scripts/memweave/sync_memory.sh [PROJECT|--all] [LIMIT]
#     --all    export EVERY project under ~/.claude/projects (cross-project corpus) — the
#              nightly cron uses this; the store ~/.uncle-j-memory becomes the global store
#     PROJECT  single project dir name under ~/.claude/projects (default: this project) — the
#              session-end Stop-hook uses this for a fast incremental ingest
#     LIMIT    optional: only the N most recent transcripts per project (default: all)
set -euo pipefail

# Derived from this script's location rather than hardcoded, so the same file works
# on Linux (/opt/proj/...) and Windows Git Bash (C:/opt/proj/...).
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Resolve both venv layouts: Windows puts the interpreter in Scripts/, POSIX in bin/.
VENV="$REPO/.venv-memweave/Scripts/python.exe"
[ -x "$VENV" ] || VENV="$REPO/.venv-memweave/bin/python"
MODE="${1:-}"
LIMIT="${2:-}"
LOCK="${TMPDIR:-/tmp}/memweave-sync.lock"

mkdir -p "$REPO/state"

# Defence in depth, not the fix. Every call site in export_transcripts.py and
# mw_search.py now names its encoding explicitly, which is what actually makes
# this correct. These two say the same thing at the process level so that any
# print() or open() added later — by us or by the memweave library, which
# index_workspace.py calls and we do not control — cannot silently fall back to
# cp1252 under Task Scheduler, where no console codepage is inherited.
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

if [ ! -x "$VENV" ]; then
  echo "[$(date -Iseconds)] sync ERROR — memweave venv missing at $VENV" >&2
  exit 1
fi

# Serialize: a concurrent sync (cron vs Stop-hook) must not race the sqlite index.
# mkdir is atomic on every filesystem and needs no flock, which MSYS/Git Bash
# does not ship.
if ! mkdir "$LOCK.d" 2>/dev/null; then
  echo "[$(date -Iseconds)] sync skipped — another sync holds $LOCK.d"
  exit 0
fi
trap 'rmdir "$LOCK.d" 2>/dev/null || true' EXIT

if [ "$MODE" = "--all" ]; then
  export_args=(--all-projects)
  scope="all-projects"
else
  # MODE empty (Stop-hook passes '') falls back to this project.
  # Claude names each transcript dir after the project path with ':' '/' '\' → '-'
  # (Linux /opt/proj/X → -opt-proj-X; Windows C:\opt\proj\X → C--opt-proj-X), so
  # derive the slug instead of hardcoding the Linux form.
  #
  # The slug must be built from the NATIVE path: under MSYS $REPO is the mounted
  # form (/c/opt/proj/X), which would yield "-c-opt-proj-X" instead of the
  # "C--opt-proj-X" Claude actually uses. cygpath -w recovers the Windows form.
  REPO_NATIVE="$REPO"
  if command -v cygpath >/dev/null 2>&1; then
    REPO_NATIVE="$(cygpath -w "$REPO" 2>/dev/null || printf '%s' "$REPO")"
  fi
  REPO_SLUG="$(printf '%s' "$REPO_NATIVE" | tr ':\\/' '---')"
  PROJECT="${MODE:-$REPO_SLUG}"
  export_args=(--project="$PROJECT")
  scope="project=$PROJECT"

  # No session has run in this project yet — nothing to export. Exit clean rather
  # than letting export_transcripts.py raise FileNotFoundError into the Stop hook.
  if [ ! -d "$HOME/.claude/projects/$PROJECT" ]; then
    echo "[$(date -Iseconds)] sync skipped — no transcripts yet for $PROJECT"
    exit 0
  fi
fi
[ -n "$LIMIT" ] && export_args+=(--limit "$LIMIT")

echo "===== [$(date -Iseconds)] memweave sync: $scope limit=${LIMIT:-all} ====="

# export_transcripts.py now exits non-zero when any single transcript failed,
# while still exporting all the others. Under `set -e` that would abort the run
# here and skip indexing entirely — so one bad transcript would keep every good
# one that was just written out of the index, which is the opposite of why the
# per-file handler exists. Capture the status, index regardless, and carry the
# failure to the exit code so the run still reports itself unsuccessful.
export_rc=0
"$VENV" "$REPO/scripts/memweave/export_transcripts.py" "${export_args[@]}" || export_rc=$?

"$VENV" "$REPO/scripts/memweave/index_workspace.py"
echo "===== [$(date -Iseconds)] sync complete ====="

if [ "$export_rc" -ne 0 ]; then
  echo "[$(date -Iseconds)] sync FAILED — export reported errors above (rc=$export_rc);" \
       "the documents that did export were still indexed" >&2
  exit "$export_rc"
fi

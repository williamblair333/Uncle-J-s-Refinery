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
#   scripts/memweave/sync_memory.sh [PROJECT] [LIMIT]
#     PROJECT  dir name under ~/.claude/projects (default: -opt-proj-Uncle-J-s-Refinery)
#     LIMIT    optional: only the N most recent transcripts (default: all)
set -euo pipefail

REPO="/opt/proj/Uncle-J-s-Refinery"
VENV="$REPO/.venv-memweave/bin/python"
PROJECT="${1:--opt-proj-Uncle-J-s-Refinery}"
LIMIT="${2:-}"
LOCK="/tmp/memweave-sync.lock"

mkdir -p "$REPO/state"

if [ ! -x "$VENV" ]; then
  echo "[$(date -Iseconds)] sync ERROR — memweave venv missing at $VENV" >&2
  exit 1
fi

# Serialize: a concurrent sync (cron vs Stop-hook) must not race the sqlite index.
exec 200>"$LOCK"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] sync skipped — another sync holds $LOCK"
  exit 0
fi

echo "===== [$(date -Iseconds)] memweave sync: project=$PROJECT limit=${LIMIT:-all} ====="
export_args=(--project="$PROJECT")
[ -n "$LIMIT" ] && export_args+=(--limit "$LIMIT")
"$VENV" "$REPO/scripts/memweave/export_transcripts.py" "${export_args[@]}"
"$VENV" "$REPO/scripts/memweave/index_workspace.py"
echo "===== [$(date -Iseconds)] sync complete ====="

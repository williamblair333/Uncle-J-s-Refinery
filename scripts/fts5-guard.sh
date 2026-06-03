#!/usr/bin/env bash
# fts5-guard.sh — DISABLED
#
# This was the primary cause of recurring FTS5 "malformed inverted index" corruption.
# It ran async at SessionStart, opening a concurrent SQLite FTS5 transaction while
# the 4am repair and session-start-autofix.sh were also accessing the DB. Concurrent
# FTS5 writes corrupt the inverted index B-tree.
#
# FTS5 health is now handled by session-start-autofix.sh, which uses venv Python
# (SQLite 3.50.x), PRAGMA quick_check, repair flock, and session flock.
#
# Do not re-enable without proper flock coordination.
exit 0

#!/usr/bin/env bash
# FTS5 integrity guard — async SessionStart safety net.
# Detects and repairs FTS5 corruption before the healthcheck reports it.
# Uses venv Python (not system sqlite3) to avoid SQLite 3.46 vs 3.50 version mismatch.
VENV=/opt/proj/Uncle-J-s-Refinery/.venv/bin
DB="$HOME/.mempalace/palace/chroma.sqlite3"
[[ -f "$DB" ]] || exit 0
"$VENV/python3" -c "
import sqlite3, sys
c = sqlite3.connect('$DB')
try:
    c.execute(\"INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('integrity-check')\")
    c.fetchall()
except Exception:
    c.execute(\"INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('rebuild')\")
    c.commit()
    print('[fts5-guard] FTS5 rebuilt at session start', file=sys.stderr)
" 2>&1 || true

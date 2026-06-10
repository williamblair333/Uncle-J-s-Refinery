#!/usr/bin/env bash
# session-start-autofix.sh — auto-repairs common startup failures, then shows healthcheck.
# Fires as a SessionStart hook. All operations are soft-fail (exit 0 always).
# Log: state/session-start-autofix.log

set -uo pipefail
REPO_ROOT="/opt/proj/Uncle-J-s-Refinery"
LOG="$REPO_ROOT/state/session-start-autofix.log"
CHROMA_DB="$HOME/.mempalace/palace/chroma.sqlite3"

ts()  { date '+%Y-%m-%d %H:%M:%S'; }
log() { printf '%s %s\n' "$(ts)" "$*" >> "$LOG" 2>/dev/null; }

# ── 0. Post-upgrade integration pending? ─────────────────────────────────────
# Flag written by async upgrade subshell (section 4 below). If the upgrade
# completed after the previous session ended, the flag will persist here.
# The post-upgrade-mcp-integration skill clears it (step 8) when done.
if [[ -f "$REPO_ROOT/state/post-upgrade-needed" ]]; then
    log "post-upgrade-needed flag found — MCP stack upgraded in a prior session, integration pending"
    printf '    NOTICE      MCP stack was upgraded in a prior session — run /post-upgrade-mcp-integration\n'
fi

# ── 1. FTS5 direct check + auto-repair (fast, no healthcheck needed) ─────────
# CRITICAL: use venv Python (SQLite 3.50.x), NOT system python3/sqlite3 (3.46.1).
# System SQLite 3.46 reading/writing FTS5 structures created by 3.50 silently corrupts
# the inverted index. This was the primary recurring corruption cause.
# Skip entirely if the 4am repair is already running.
VENV_PY="$REPO_ROOT/.venv/bin/python3"
if [[ -f "$CHROMA_DB" ]] && [[ -x "$VENV_PY" ]]; then
    if ! flock -n /tmp/mempalace-repair.lock true 2>/dev/null; then
        log "FTS5 check skipped — repair lock held"
    else
        FTS5_STATUS=$(flock -n /tmp/mempalace-fts5-session.lock \
            "$VENV_PY" - "$CHROMA_DB" 2>/dev/null <<'PYEOF' || echo "unknown"
import sqlite3, sys
db = sys.argv[1]
try:
    result = sqlite3.connect(db, timeout=5).execute('PRAGMA quick_check').fetchone()[0]
    print('ok' if result == 'ok' else 'corrupt')
except Exception:
    print('unknown')
PYEOF
)
        if [[ "$FTS5_STATUS" == "corrupt" ]]; then
            log "FTS5 corrupt detected — rebuilding (venv Python, SQLite 3.50)"
            FTS5_REBUILD_LOG=$(flock -x /tmp/mempalace-fts5-session.lock \
                "$VENV_PY" - "$CHROMA_DB" 2>&1 <<'PYEOF'
import sqlite3, sys
db = sys.argv[1]
conn = sqlite3.connect(db, timeout=60)
conn.execute("INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('rebuild')")
conn.commit()
qc = conn.execute('PRAGMA quick_check').fetchone()[0]
conn.close()
if qc != 'ok':
    raise RuntimeError(f'still corrupt after rebuild: {qc}')
print('ok')
PYEOF
)
            if echo "$FTS5_REBUILD_LOG" | grep -q "^ok$"; then
                log "FTS5 rebuild: OK"
                printf '    AUTO-FIXED  MemPalace FTS5 rebuilt\n'
            else
                log "FTS5 rebuild: FAILED — $FTS5_REBUILD_LOG"
            fi
        fi
    fi
fi

# ── 2. jcodemunch staleness — compare stamp file vs git HEAD (fast, local) ───
STAMP="$REPO_ROOT/state/jcodemunch-last-indexed.sha"
CURRENT_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)
INDEXED_SHA=$(cat "$STAMP" 2>/dev/null | tr -d '[:space:]' || true)

if [[ -n "$CURRENT_SHA" && "$INDEXED_SHA" != "$CURRENT_SHA" ]]; then
    log "jcodemunch stale (indexed=${INDEXED_SHA:-never} current=$CURRENT_SHA) — reindexing"
    if bash "$REPO_ROOT/scripts/jcodemunch-reindex.sh" >> "$LOG" 2>&1; then
        log "jcodemunch reindex: OK"
        printf '    AUTO-FIXED  jcodemunch reindexed\n'
    else
        log "jcodemunch reindex: FAILED"
    fi
fi

# ── 3. Run healthcheck once — capture output for display + stack detection ────
HEALTH_OUT=$(CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI \
    bash "$REPO_ROOT/healthcheck.sh" --quick 2>&1 || true)

# ── 4. Stack packages behind HEAD — async upgrade (avoids blocking session) ───
if echo "$HEALTH_OUT" | grep -q "stack-not-at-head"; then
    log "Stack packages behind HEAD — launching async upgrade"
    (
        # Guard against concurrent upgrade runs from simultaneous session starts
        exec 9>/tmp/uncle-j-uv-upgrade.lock || { log "Stack upgrade lock unavailable — skipping"; exit 0; }
        flock -n 9 || { log "Stack upgrade already running — skipping"; exit 0; }
        cd "$REPO_ROOT"
        if uv lock --upgrade-package jcodemunch-mcp \
                   --upgrade-package jdatamunch-mcp \
                   --upgrade-package jdocmunch-mcp \
                   --upgrade-package mempalace \
            && uv sync --inexact; then
            touch "$REPO_ROOT/state/post-upgrade-needed"
            log "Stack upgrade: OK (state/post-upgrade-needed flag created)"
        else
            log "Stack upgrade: FAILED (network or resolution error)"
        fi
    ) >> "$LOG" 2>&1 &
    disown
    printf '    AUTO-FIX    MCP stack upgrading async (tail state/session-start-autofix.log)\n'
fi

# ── Display final healthcheck output ─────────────────────────────────────────
echo "$HEALTH_OUT" | tail -5
exit 0

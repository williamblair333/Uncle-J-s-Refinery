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

# ── 1. FTS5 direct check + auto-repair (fast, no healthcheck needed) ─────────
if [[ -f "$CHROMA_DB" ]]; then
    FTS5_STATUS=$(python3 -c "
import sqlite3
try:
    sqlite3.connect('$CHROMA_DB', timeout=5).execute(
        \"SELECT * FROM embedding_fulltext_search('x')\").fetchmany(1)
    print('ok')
except Exception as e:
    err = str(e).lower()
    print('corrupt' if any(k in err for k in ('fts5','corrupt','malformed','disk image')) else 'ok')
" 2>/dev/null || echo "unknown")

    if [[ "$FTS5_STATUS" == "corrupt" ]]; then
        log "FTS5 corrupt detected — rebuilding"
        if sqlite3 -cmd ".timeout 30000" "$CHROMA_DB" \
               "INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('rebuild');" \
               >> "$LOG" 2>&1; then
            log "FTS5 rebuild: OK"
            printf '    AUTO-FIXED  MemPalace FTS5 rebuilt\n'
        else
            log "FTS5 rebuild: FAILED (DB locked — will retry next session)"
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
        cd "$REPO_ROOT"
        if uv lock --upgrade-package jcodemunch-mcp \
                   --upgrade-package jdatamunch-mcp \
                   --upgrade-package jdocmunch-mcp \
                   --upgrade-package mempalace \
            && uv sync --inexact; then
            touch "$REPO_ROOT/state/post-upgrade-needed"
            log "Stack upgrade: OK (post-upgrade-mcp-integration flag set)"
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

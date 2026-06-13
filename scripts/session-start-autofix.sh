#!/usr/bin/env bash
# session-start-autofix.sh — auto-repairs common startup failures, then shows healthcheck.
# Fires as a SessionStart hook. All operations are soft-fail (exit 0 always).
# Log: state/session-start-autofix.log

set -uo pipefail
REPO_ROOT="/opt/proj/Uncle-J-s-Refinery"
LOG="$REPO_ROOT/state/session-start-autofix.log"

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

# ── 1. jcodemunch staleness — compare stamp file vs git HEAD (fast, local) ───
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

# ── 2. Run healthcheck once — capture output for display + stack detection ────
HEALTH_OUT=$(CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI \
    bash "$REPO_ROOT/healthcheck.sh" --quick 2>&1 || true)

# ── 3. Stack packages behind HEAD — async upgrade (avoids blocking session) ───
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

#!/usr/bin/env bash
# Wrapper: run health check then start mempalace MCP server.
# Health check failures are logged but never block startup.
set -uo pipefail

VENV=/opt/proj/Uncle-J-s-Refinery/.venv
LOG=/opt/proj/Uncle-J-s-Refinery/state/mempalace-health.log
HEALTH=/opt/proj/Uncle-J-s-Refinery/mempalace-health.py

if [[ -f "$HEALTH" ]]; then
    "$VENV/bin/python" "$HEALTH" >> "$LOG" 2>&1 || {
        echo "$(date -Iseconds) WARNING: mempalace health check failed (see $LOG)" >> "$LOG"
    }
fi

exec "$VENV/bin/python" -m mempalace.mcp_server "$@"

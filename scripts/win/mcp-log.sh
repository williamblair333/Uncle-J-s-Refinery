#!/usr/bin/env bash
# PreToolUse(mcp__.*) hook: append each MCP tool invocation to a log.
#
# Replaces the previous inline hook, which shelled out to `python3` — absent on
# this Windows host. Uses the repo venv interpreter instead, resolving the
# Windows (Scripts/) and POSIX (bin/) venv layouts.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || exit 0

"$PY" -c "
import json, sys, datetime, os
d = json.load(sys.stdin)
p = os.path.expanduser('~/.claude/state/mcp-tool-log.txt')
os.makedirs(os.path.dirname(p), exist_ok=True)
with open(p, 'a', encoding='utf-8') as fh:
    fh.write('[{}] {}\n'.format(
        datetime.datetime.now().strftime('%H:%M:%S'), d.get('tool_name', '?')))
" 2>/dev/null || true
exit 0

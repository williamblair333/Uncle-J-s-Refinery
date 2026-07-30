#!/usr/bin/env bash
# PreToolUse(Bash) hook: block `git commit` unless the docs .session-end.yml
# declares mandatory are staged. Checkpoint commits ("chk: ...") are exempt.
#
# Replaces the previous inline hook, which used `jq` to parse the hook payload
# and to emit the decision JSON. `jq` is not present on this Windows host, so the
# guard could never fire. The repo venv interpreter does both jobs instead.
#
# The mandatory list is READ FROM .session-end.yml rather than hardcoded. The
# inline hook it replaced hardcoded CHANGELOG.md + HANDOFF.md + docs/RELIABILITY.md
# while .session-end.yml declares only the first two, so the guard blocked commits
# the session-end check had just passed. It also ignored the config's
# trigger.file_types gate, which exists so doc-only commits pass freely. Both
# divergences came from the same cause: two gates encoding the same policy in two
# places. There is now one source of truth.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$ROOT/.venv/bin/python"

INPUT="$(cat)"

# Fail open: if we cannot parse the payload, never block the user's commit.
[ -x "$PY" ] || exit 0

CMD="$(printf '%s' "$INPUT" | "$PY" -c \
  "import json,sys
try:
    print(json.load(sys.stdin).get('tool_input', {}).get('command', ''))
except Exception:
    print('')" 2>/dev/null || true)"

printf '%s' "$CMD" | grep -qE '\bgit\b.*\bcommit\b' || exit 0
printf '%s' "$CMD" | grep -qE '\-m[[:space:]]+.?chk:' && exit 0

STAGED="$(git -C "$ROOT" diff --cached --name-only 2>/dev/null || true)"
[ -n "$STAGED" ] || exit 0

MISSING="$(printf '%s' "$STAGED" | "$PY" -c "
import sys, os, yaml

root = sys.argv[1]
staged = [l.strip() for l in sys.stdin if l.strip()]

try:
    with open(os.path.join(root, '.session-end.yml')) as fh:
        cfg = yaml.safe_load(fh) or {}
except Exception:
    # No readable config means no declared policy to enforce.
    sys.exit(0)

# trigger.file_types gates the whole check: a commit touching none of these is
# doc/config-only and passes freely, per the comment in .session-end.yml.
types = (cfg.get('trigger') or {}).get('file_types') or []
if types and not any(f.endswith(tuple(types)) for f in staged):
    sys.exit(0)

missing = [f for f in (cfg.get('mandatory') or []) if f not in staged]
print(' '.join(missing))
" "$ROOT" 2>/dev/null || true)"

[ -z "${MISSING// /}" ] && exit 0

"$PY" -c \
  "import json,sys
print(json.dumps({'continue': False,
                  'stopReason': 'Commit blocked - update first: ' + sys.argv[1]}))" \
  "$MISSING"
exit 0

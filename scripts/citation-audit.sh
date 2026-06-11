#!/usr/bin/env bash
# scripts/citation-audit.sh — Claude Code Stop hook.
# Greps the session transcript for URLs, cross-checks against WebFetch/gh evidence
# in the same transcript, appends verified/unverified records to
# state/citation-audit.jsonl. Deterministic; exit 0 always (like the other Stop hooks).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Prefer repo .venv python; fall back to python3. Never fail the hook.
PY="$SCRIPT_DIR/../.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3 || true)"
[[ -n "$PY" ]] || exit 0
"$PY" "$SCRIPT_DIR/citation_audit.py" </dev/stdin >/dev/null 2>&1 || true
exit 0

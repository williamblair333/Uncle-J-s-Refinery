#!/usr/bin/env bash
# Append a validated factual-correction event to state/corrections.jsonl.
# Deterministic capture — NO LLM. Invoked by Claude when the user corrects a
# factual error (see CLAUDE.md), or by hand.
# Usage: scripts/log-correction.sh <component> <summary...>
set -euo pipefail
cd "$(dirname "$0")/.."

COMPONENT="${1:-}"
shift || true
SUMMARY="$*"

if [[ -z "$COMPONENT" || -z "$SUMMARY" ]]; then
  echo "usage: log-correction.sh <component> <summary>" >&2
  exit 2
fi

mkdir -p state
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Build the JSON with python3 for safe escaping — never hand-concat user text.
python3 - "$TS" "$COMPONENT" "$SUMMARY" <<'PY' >> state/corrections.jsonl
import json, sys
ts, component, summary = sys.argv[1], sys.argv[2], sys.argv[3]
print(json.dumps({"ts": ts, "component": component, "summary": summary}, ensure_ascii=False))
PY
echo "logged correction: $COMPONENT — $SUMMARY"

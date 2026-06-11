#!/usr/bin/env bash
# Pay-for-itself audit — runs all collectors then builds the scorecard.
# Deterministic; no LLM calls; safe to re-run anytime.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv/bin/python
for c in collect_token_cost collect_maintenance collect_benefits build_scorecard; do
  "$PY" "scripts/audit/${c}.py"
done
echo "Done. Review state/payoff-scorecard.md, then run the judgment pass in-session."

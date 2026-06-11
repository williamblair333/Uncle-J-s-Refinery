#!/usr/bin/env bash
# Recall benchmark runner — deterministic, no LLM. Default label chroma-baseline.
# Usage: scripts/bench/run-recall-bench.sh [label] [k]
set -euo pipefail
cd "$(dirname "$0")/../.."
LABEL="${1:-chroma-baseline}"
K="${2:-5}"
.venv/bin/python scripts/bench/run_recall_bench.py --label "$LABEL" --k "$K"
echo "Done. Results: state/recall-bench/results-${LABEL}.json"

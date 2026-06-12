#!/usr/bin/env bash
# Recall benchmark runner — deterministic, no LLM. Default label chroma-baseline.
# Scores the checked-in probe set against the live palace and writes
# state/recall-bench/results-<label>.json (gitignored). The summary line reports
# vector_failure_rate — a nonzero rate means the run is partly BM25, so the
# recall number is NOT a clean vector measurement.
# Usage: scripts/bench/run-recall-bench.sh [label] [k]
set -euo pipefail
cd "$(dirname "$0")/../.."
LABEL="${1:-chroma-baseline}"
K="${2:-5}"
.venv/bin/python scripts/bench/run_recall_bench.py --label "$LABEL" --k "$K"
echo "Done. Results: state/recall-bench/results-${LABEL}.json"

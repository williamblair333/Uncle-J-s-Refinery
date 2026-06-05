#!/usr/bin/env bash
set -euo pipefail
VENV=/opt/proj/Uncle-J-s-Refinery/.venv
FORK="git+https://github.com/williamblair333/turbovecdb.git@fix/security-findings"

echo "Installing turbovecdb from patched fork..."
uv pip install "$FORK" --quiet
"$VENV/bin/python3" -c "import turbovecdb; print('turbovecdb', turbovecdb.__version__, 'ok')"

# Register crons (idempotent: remove old, add new)
PROJ=/opt/proj/Uncle-J-s-Refinery

crontab -l 2>/dev/null | grep -v "uncle-j-turbovecdb\|turbovecdb-sync\|turbovecdb-benchmark\|turbovecdb-report" | \
  { cat; \
    echo "# uncle-j-turbovecdb-sync"; \
    echo "30 3 * * * cd $PROJ && CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI nice -n 19 .venv/bin/python3 scripts/turbovecdb-sync.py >> state/turbovecdb-sync.log 2>&1"; \
    echo "# uncle-j-turbovecdb-benchmark"; \
    echo "0 5 * * 0 cd $PROJ && CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI .venv/bin/python3 scripts/turbovecdb-benchmark.py >> state/turbovecdb-benchmark.log 2>&1"; \
    echo "# uncle-j-turbovecdb-report"; \
    echo "0 6 * * 0 cd $PROJ && bash scripts/turbovecdb-report.sh >> state/turbovecdb-report.log 2>&1"; \
  } | crontab -

echo "Crons registered:"
crontab -l | grep turbovecdb

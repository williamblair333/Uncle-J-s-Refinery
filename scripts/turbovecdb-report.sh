#!/usr/bin/env bash
set -euo pipefail
cd /opt/proj/Uncle-J-s-Refinery
VENV_PY=.venv/bin/python3
LOG=state/turbovecdb-eval.jsonl
COMMENT_ID="DC_kwDOR5_Rks4BBi85"

[[ -f "$LOG" ]] || { echo "No eval log yet — skipping report"; exit 0; }

# Build markdown table from all log entries
TABLE=$("$VENV_PY" - << 'EOF'
import json, sys

rows = []
with open("state/turbovecdb-eval.jsonl") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        for result in r.get("results", []):
            rows.append({
                "date": r["timestamp"][:10],
                "drawers": result["total_drawers"],
                "c_p50": result["chroma_p50_ms"],
                "c_p95": result["chroma_p95_ms"],
                "t_p50": result["tvdb_p50_ms"],
                "t_p95": result["tvdb_p95_ms"],
                "recall": result["recall_at_10_mean"],
                "n": result["n_queries"],
            })

print("| Date | Drawers | Chroma p50ms | Chroma p95ms | TurboVec p50ms | TurboVec p95ms | Recall@10 | Queries |")
print("|------|---------|-------------|-------------|---------------|---------------|-----------|---------|")
for row in rows:
    print(f"| {row['date']} | {row['drawers']:,} | {row['c_p50']} | {row['c_p95']} | {row['t_p50']} | {row['t_p95']} | {row['recall']:.3f} | {row['n']} |")
EOF
)

BODY="**Scale test update — weekly benchmark (290K+ drawers, MiniLM 384-d, k=10)**

${TABLE}

*Methodology: 200 random drawer vectors sampled from ChromaDB, used as query vectors against both backends. Recall@10 = |top-10 overlap| / 10. Same machine, sequential runs.*"

# Post via GraphQL updateDiscussionComment
"$VENV_PY" - << PYEOF
import subprocess, json, sys

mutation = {
    "query": """mutation(\$commentId: ID!, \$body: String!) {
  updateDiscussionComment(input: {commentId: \$commentId, body: \$body}) {
    comment { url }
  }
}""",
    "variables": {
        "commentId": "${COMMENT_ID}",
        "body": r"""${BODY}"""
    }
}
result = subprocess.run(
    ["gh", "api", "graphql", "--input", "-"],
    input=json.dumps(mutation), capture_output=True, text=True
)
print(result.stdout)
if result.returncode != 0:
    print("STDERR:", result.stderr, file=sys.stderr)
    sys.exit(1)
PYEOF

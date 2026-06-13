---
description: Show a weekly session efficiency table from Langfuse — traces, tool calls, tokens, and high-token flags
allowed-tools: Bash
---

Show the Uncle J's Refinery session stats report.

Steps:

1. Verify the repo root is `/opt/proj/Uncle-J-s-Refinery` or a descendant.
   If not, say so and stop.

2. Execute:
   ```
   bash /opt/proj/Uncle-J-s-Refinery/features/session-stats/stats.sh
   ```

3. Print the markdown table as-is. Do not reformat it.

4. After the table, note any rows flagged ⚠ high and suggest:
   - Check those sessions for large file reads that jcodemunch could have replaced
   - Check if memweave was queried at the start (prior-art-check)

5. If Langfuse credentials are missing or the API is unreachable, say so
   and suggest: `bash /opt/proj/Uncle-J-s-Refinery/install-langfuse.sh`

Do not attempt to fix failures — stats.sh is authoritative.

---
description: Run the Uncle J's Refinery dream synthesizer — mine past Langfuse traces and write playbooks to MemPalace
allowed-tools: Bash
---

Run the dreaming synthesizer for Uncle J's Refinery.

Steps:

1. Verify the repo root is `/opt/proj/Uncle-J-s-Refinery` or a descendant.
   If not, say so and stop — dream.sh uses absolute stack paths.

2. Execute:
   ```
   bash /opt/proj/Uncle-J-s-Refinery/features/dreaming/dream.sh
   ```

3. Report:
   - The number of traces processed.
   - Whether MemPalace was updated.
   - Whether `~/.claude/CLAUDE.md` was updated.
   - The path of the output file written.
   - Any `warn` lines from stderr.

4. If Langfuse credentials are missing or the server is unreachable,
   say so and suggest: `bash /opt/proj/Uncle-J-s-Refinery/install-langfuse.sh`

To run in dry-run mode (no writes): `bash .../dream.sh --dry-run`

Do not attempt to fix failures — dream.sh is authoritative.

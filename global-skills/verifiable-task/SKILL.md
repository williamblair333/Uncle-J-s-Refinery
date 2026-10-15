---
name: verifiable-task
description: Use when about to delegate work to another agent or model — a subagent, agy (ask_agy), the local model (ask_local), Codex, a background job — or when about to report delegated work as done.
---

# verifiable-task

An agent's own "DONE" is not evidence: agy has answered "DONE" after its command was
blocked. Models do best where the result can be checked, so decide the check before you
hand the work off, not after it comes back.

## Before delegating, write three lines

1. **Check:** the command, test, count, regex or exact expected output that proves the
   result. It must be something you can run or compare, not "looks right".
   - Rows in = rows out + rows rejected.
   - Every value matches `^\+[1-9]\d{1,14}$`.
   - `pytest tests/test_x.py` passes.
   - The `path:line` hits match your own search.
2. **Where it runs:** you run it on what comes back. Never the helper reporting on itself.
3. **If it fails:** retry once with the failure quoted, or do the work yourself and say so.

Put the check in the delegation prompt too. A helper that knows the bar does better work,
but its claim to have met the bar still counts for nothing.

## Pick the route by whether a check exists

| Task | Route |
|---|---|
| Mechanical (convert, dedupe, rename, count) | Have the helper write a **script**, review the script, run it, check the output. Don't have a model transform the data itself. |
| Checkable (code with tests, a search with known hits) | Delegate with the check in the prompt; run the check yourself. |
| Judgment only (a tagline, a summary, a design call) | No check exists, so this is low-yield to delegate. Treat the result as a draft for the user to pick from, or get a second opinion with the `referee` skill. Say which. |
| Decides something with consequences (a contract term, a security call) | The helper may locate; you read the source it points to before answering. |

## Reporting back

Report what the check measured, not what the helper said: "4,012 rows in, 3,640 out,
372 merged, 0 phone values fail E.164", not "agy says it's done". If the check didn't run,
the task isn't done. Say that.

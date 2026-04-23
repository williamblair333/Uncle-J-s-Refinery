---
name: per-task-review-cycle
description: Implement → spec review → quality review → targeted fix → re-review cycle for multi-task subagent development. Use when executing an implementation plan where each task needs independent verification before moving to the next.
type: process
---

# Per-Task Review Cycle

Use this within a `superpowers:subagent-driven-development` session when tasks have verifiable specs and code quality standards that must be confirmed before merging.

## When to use

- Executing a multi-task plan where each task has a written spec
- Each task produces a standalone file or feature (not deeply interleaved)
- You want to catch issues per task rather than at the end

## Cycle per task

implementer subagent
    → spec reviewer subagent       (parallel if independent)
    → quality reviewer subagent    (parallel if independent)
    → [if issues] targeted fixer subagent
    → re-review only the fixed portions
    → APPROVED → next task

Run spec and quality reviews **in parallel** after implementation completes — they're independent reads.

## Override protocol

When a reviewer flags something that is **architecturally correct by contract** (e.g., `trap 'exit 0' ERR` in a Stop hook, intentional silent exit, framework-mandated behavior):

1. Identify the specific reviewer error (wrong lens, wrong contract model)
2. State the correct invariant explicitly
3. Override to APPROVED with documented rationale
4. Do not dispatch a fix for correct code

## Final integration review

After all tasks complete, run one cross-task review subagent scoped to the full diff. Catches:
- Duplicate flags or args across files
- Inconsistent PATH/env injection patterns
- Missing error propagation contracts

## Checklist

- [ ] Implementer dispatched
- [ ] Spec + quality reviews run (in parallel)
- [ ] Issues triaged: real fix vs. reviewer error
- [ ] Targeted fixer dispatched for real issues only
- [ ] Re-review confirms fixes
- [ ] Task marked APPROVED
- [ ] Final cross-task review after all tasks done
- [ ] Changelog written from meaningful commits

## Key signals for reviewer override

| Reviewer claim | Real situation | Override? |
|---|---|---|
| "Missing error handling" | Stop hook must exit 0 on all paths | Yes |
| "Source path wrong" | Reviewer assumed wrong lib file | Yes — grep to confirm |
| "Executable bit missing" | `100755` confirmed in git | Yes |
| "Duplicate flag" | Actually distinct flags (`-p` vs `--print`) | No — real bug |

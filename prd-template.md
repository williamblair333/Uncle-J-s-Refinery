# PRD — <short title>

> This is the stable memory for a Ralph loop. The agent re-reads this
> file every iteration. Keep it structured. Update the Progress section
> at the end of each iteration.

## Goal

<One paragraph. What does "done" look like? Written in terms a user
would check, not implementation details.>

## Non-goals

<What this PRD is explicitly NOT about. Keeps scope honest.>

- <e.g., migrating to a new DB>
- <e.g., fixing unrelated test flakes>

## Context and prior work

<Links to docs, prior PRs, prior conversations. If MemPalace has
history on this topic, the agent should surface it here on iteration 1
and leave it for later iterations to reference.>

## Acceptance criteria

<Checkboxes. The done-gate can key off these.>

- [ ] <criterion 1 — specific, checkable>
- [ ] <criterion 2>
- [ ] All changed symbols have tests
- [ ] `get_pr_risk_profile` < 0.65
- [ ] No new untested symbols

## Success Rubric (optional — for --rubric mode)

<If using ralph-harness.sh --rubric, paste the rubric here or reference
the path. The outcomes grader reads this in a fresh context after each
iteration. Leave blank if not using --rubric.>

See: `global-skills/outcomes/RUBRIC.md.template` for the starter template.

## Agent Decomposition (optional — for --decompose mode)

<If using ralph-harness.sh --decompose, the orchestrator skill reads this
PRD and decides how to split it. To guide decomposition, you can add hints
here about which parts are parallelizable and which must run in sequence.>

Example hints:
- "Research tasks (MemPalace + docs) can run in parallel with code analysis."
- "Implementation must follow research (serialize tasks 2 and 3)."
- "Max 4 sub-agents — this is a focused change."

Leave blank to let the orchestrator decide based on the PRD content alone.

## Constraints

<Things the agent must respect.>

- Use jcodemunch / serena for navigation; don't Read whole files.
- Touch the fewest symbols possible.
- <e.g., don't touch the public API of module X>

## Progress

<!--
The FIRST non-empty line here is what the done-gate reads.
Start with `DONE` (uppercase, standalone) to signal completion.
Otherwise prepend a one-line status for the latest iteration.
-->

(iteration log — newest on top)

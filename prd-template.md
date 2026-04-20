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

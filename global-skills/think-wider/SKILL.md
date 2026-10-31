---
name: think-wider
description: Use when planning the next stretch of work, writing or rewriting a STANDARDS.md (expert-bar calls it), stuck after two fixes that didn't hold, choosing between approaches, or when the user asks "is this the best approach", "how would an expert in another field do this", "what are we missing", "think outside the box". Not for routine edits, lookups or bug fixes with a known cause.
---

# Think Wider

## Overview

Left alone, a plan stays inside the problem's own field. It comes out competent and it
matches what everyone else in that field would write. The ideas that change outcomes usually
come from a field that already solved the same *shape* of problem under another name.
**Core principle: strip the problem down to its shape, borrow from fields that solved that
shape, check everything against the hard constraints and the base rate, and label each
borrowed idea as a hypothesis until a test proves it.**

## When it fires

- Planning the next stretch of work, or writing a STANDARDS.md (expert-bar step 3).
- Stuck: two fixes in a row didn't hold, or every option on the table feels the same.
- Choosing between approaches, or the user asks whether this is the best way.

It costs a few hundred tokens of thought. Don't run it on edits, lookups or known-cause bugs.

## Output contract

Before the plan, write a **Wider** block. It has these five parts, in order. Every part is
required.

1. **Shape.** One sentence that states the problem with the domain nouns removed. Example:
   "judge whether a change helps when every trial runs in a noisy world whose random events
   are unknown in advance." No project jargon.
2. **Transfers (2–3).** Each one names a field *outside* the project's own that solved this
   shape, then the mechanism it used, then what that mechanism means here. Use this form:
   "**<Field>** has this shape: <their situation>. They <mechanism>. Here: <concrete action>."
   The fields must cross a real boundary (medicine, aviation, manufacturing, ecology, law,
   finance, logistics, sports, military…). Software → other software doesn't count.
3. **First principles.** The constraints that can't be negotiated (time, money, physics,
   information, who controls what). From those alone, name one option the current setup
   would not have suggested.
4. **Outside view.** A reference class *outside this project* (other teams' projects, other
   systems, published studies), its base rate as a number, and how that number shifts the
   plan. This project's own log is the inside view, so it doesn't count here. If you don't
   know the number, say so and name the cheapest way to get it. Never invent one.
5. **Ideas to try.** Each transfer or first-principles option that you keep, written as a
   hypothesis: `idea`, `from` (the field), `test` (the cheapest run that would show it
   works), `kill` (the result that drops it).

**If no transfer solves the whole shape, build one.** This applies whenever every transfer
is partial or none fits. Name the contradiction that blocks the obvious answer ("it must be
forgotten, yet the source stays"). Split the problem into the jobs a solution must do, and
take a mechanism from a different field for each job. Compose them into one named design and
show which job each part covers. The composed design goes in ideas-to-try like any other.
**If nothing composes either,** say plainly that no full solution was found. Name the
constraint that blocks it, then name the largest part that *can* be solved. Never pass off a
weak analogy as a solution.

Then write the plan, and name the idea each step uses.

## Where the output goes

- **In a STANDARDS.md:** ideas go in an `ideas:` list next to `standards:` in the same yaml
  block, with fields `id, idea, from, test, kill, status` (`untested | testing | paid-off |
  dropped`). An idea gets promoted to a standard only after its test has paid off.
- **In a plan or reply:** the Wider block sits above the plan, so the user can see each
  mapping and learn from it.
- **Learning:** when you come back to a STANDARDS.md, update the status of each idea before
  you add new ones. Note which source fields actually paid off, because that tells you where
  to look first next time.

## Common mistakes

| You catch yourself… | Instead |
|---|---|
| Naming a field with no mechanism ("like aviation, be careful") | Name the exact practice (the checklist read aloud before takeoff) and the action it maps to here |
| Picking the nearest field (testing → other testing) | Cross a boundary: who else must judge a change in a noisy world? Clinical trials, crop breeding, sports analytics |
| A base rate that sounds right ("most projects fail") | Give a number with its source, or write "unknown: get it by <cheapest check>" |
| Using this project's own history as the reference class | That's the inside view. Ask how this kind of thing goes for *other people*, then compare |
| Putting a transfer straight into the plan as fact | It goes in ideas-to-try with a test and a kill result first |
| A Wider block that changes nothing in the plan | If no step uses an idea, the block was decoration. Build a composed design from the jobs, or name the constraint that blocks every option |
| Stopping at "no field has solved this" | That's when you build: contradiction, jobs, one mechanism per job, compose |

## Limits

Analogies mislead when the shape only matches on the surface. Run the test before you
trust a transfer. The user's goal outranks any borrowed idea.

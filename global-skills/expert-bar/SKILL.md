---
name: expert-bar
description: Use when a project has no STANDARDS.md (the session-start notice says so), when its phase changes, before planning the next stretch of work, or when the user keeps asking meta-questions such as "why didn't you…", "why did I have to ask", "is this the best approach", "why not from the get-go". Writes or rewrites the project's expert bar, the list of what a senior practitioner of its domain would already have in place.
---

# Expert Bar

## Overview

Working the bug queue in front of you produces fixes, not a well-run project. A senior
engineer arrives with a picture of what good looks like in their field and builds toward it
without being asked. `STANDARDS.md` writes that picture down, so every session starts from it
rather than from the last ticket. **Core principle: the bar comes from the field, not from the
repo, and every claim on it points at evidence.**

## When it fires

- The session-start notice says `no STANDARDS.md`.
- The project's phase changed (prototype → reliable → released, research → build).
- You're about to plan the next stretch of work.
- The user asked a meta-question: "why didn't you…", "why did I have to ask", "is this the
  fastest/best way", "don't we have N of those, why only one". That's the bar showing up late.

## The move, in order

1. **Name the goal** in one sentence, from PRODUCT.md or the user's own words.
2. **Name the field and the seats.** What domain is this (game QA and release engineering,
   forensics, payroll, embedded firmware…), and which senior roles would own it? Enumerate
   *their* canon before looking at the repo. What's in your context (this repo's habits, the
   tooling you have, last week's bug) is availability, not the standard.
3. **List what those people would already have in place** for this goal and phase: harnesses,
   fixtures, gates, telemetry, runbooks, release practice. Make each one testable, a single
   bar per item.
4. **Check the repo for each one.** Set `status` to open, partial, done or n/a. Done and partial
   need `evidence`: a repo path or `just <recipe>`. Open items say concretely what's missing.
   Count a partial as open.
5. **Rank by impact on the goal**, highest first. 10–25 items.
6. **Write `STANDARDS.md`** at the repo root, in the format below, then run
   `python3 $STACK_ROOT/features/product-quality/standards_check.py --check .`.
   It flags any done or partial item whose evidence doesn't exist.
7. **Work from it.** The next work is the top open gap unless the user picks another. Every
   status report names the gap it moved.

## Format

Prose header (whose seat, the goal, "ranked by impact"), then one fenced yaml block:

```yaml
phase: making it reliable — rulers play run after run unattended
standards:
  - id: fixed-bench-save            # stable slug
    area: QA                        # the field's own category
    bar: Every bench suite starts from one fixed, quiet test save, never a copy of a live campaign
    why: a game QA lead never tests on a world whose next event is unknown
    status: open                    # open | partial | done | n/a
    evidence: the bench restores the live save; a Pope died mid-suite 10-31   # done/partial: path or `just x`
```

Full example: `/opt/proj/games/mtw2/STANDARDS.md` (18 items across QA, rulers, live-ops and release).

## Quick reference

| You catch yourself… | Instead |
|---|---|
| Listing lint, CI and coverage for every project | Name the field first; list its own practices |
| Writing "improve testing" | One bar you can check: "every bug gets a failing bench case before its fix merges" |
| Marking done because a directory exists | Done means the bar is met; the checker only proves the evidence exists |
| Fixing the next ticket without opening the file | Read the top gaps first; say which one the work moves |
| Keeping the bar after the phase changed | Rewrite it; a prototype's bar is not a release's |

## Limits

The checker verifies that the evidence exists, not that the bar is met. The `why` and the
ranking are judgment; when the user disagrees with an item, they're right about their goal.

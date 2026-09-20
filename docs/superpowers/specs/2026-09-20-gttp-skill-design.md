# gttp — design and evaluation record

2026-09-20. Source: two uploaded skills, `gttp` and `constraint-bricolage`, merged into one.

## What the skill is for

A user proposes a specific means — a material, a product, a hack — and asks whether it works. Two
symmetric failures follow: dismissing an unusual idea because nobody does it, and validating one
because the user pushed back. Both come from answering the request as stated instead of the goal
behind it. The skill extracts the goal, makes every class of solution compete on one metric, and
kills candidates on mechanism.

## Why the two skills were merged

Their triggers overlapped ("can I use X instead" matched both), they handed off to each other in a
cycle with no termination rule, and `constraint-bricolage` read `references/` from the *other*
skill's folder — broken if installed alone. The improvise path is now a box inside Step 3, and
`gttp`'s description carries the bricolage triggers.

## Method

TDD per `superpowers:writing-skills`: baseline first, then the skill, then close what the runs
found. 12 scenarios, none of which appears as a worked example in either skill — the uploaded
evals reused the skill's own roof-fabric example and its log entries, so passing them tested
recall, not generalization. Every reply was graded blind by a separate agent against the
assertions; conditions were unblinded only after scoring.

## Results

| Condition | Assertions | Mean quality (1–5) |
|---|---|---|
| No skill (round 1, 7 scenarios) | 20/29 | 3.86 |
| Uploaded skill | 25/29 | 3.57 |
| Revised skill | 28/29 | 4.57 |
| No skill (round 2, 4 new scenarios) | 14/16 | 4.00 |
| Revised skill (round 2, 8) | 33/34 | 4.75 |

The uploaded skill passed more assertions than no skill while giving *worse* advice. Two causes:
the report template ran on a $5 toilet flapper (777 words against 400 unaided), and the improvise
path plus "unknowns are costs to price, not vetoes" produced a machined pressure-canner regulator
weight, with target masses, called "a legitimate copy of the factory design".

Trigger tests, 3 reps per description, 16 requests including five software-choice negatives:
the uploaded description fired on "which Python library should I use" in 3/3 runs and on coding
tasks in 1/3; the revised description scored 48/48.

## What the runs changed in the skill

| Finding | Change |
|---|---|
| Template bloat on trivial fixes | Step 1 routes; short answer ≤150 words |
| Improvised safety-critical part recommended | Hard-limit route: no dimensions, masses, formulas, build or bypass steps |
| "I'll calibrate it" used to license fabrication | Named and refused in the same row |
| Bypass/disable not covered by "substitute" | Both verbs in the route condition |
| Figures stated as fact | Cite-or-label rule on every route, prose included |
| 4 of 7 runs wrote into the skill's own `references/` | Step 6: user notes only, `$GTTP_NOTES_DIR` or the vault, never the skill folder |
| Same idea logged twice across turns | Search the log first; "seen again" line only when something new was learned |
| Repurposed property assumed, not checked | Step 4 mechanism covers bond, heat, and fit; library gained a fit-geometry lever |
| Stopgap offered without its own caveats | Stated in the always-on rules and the Hard-limit row |
| Full analysis drifting to ~1,000 words | ~600-word cap |

Adversarial review before shipping (27 findings) supplied the route-ordering, hard-limit-scope and
log-dedup fixes; each was re-tested after the edit.

## Known limits

- The hard-limit refusal is a policy choice: it declines to help fabricate a safety-critical part
  even where a competent shop could verify the result. Loosen the first route row to change that.
- `references/mechanism-library.md` ships with the skill and is not edited at runtime. Mechanisms
  that prove out in the user's log are promoted by a reviewed change.
- Both graders and the review agent were Claude; the citation-labeling assertion is the most
  subjective one they applied.

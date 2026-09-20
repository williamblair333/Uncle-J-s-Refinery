---
name: gttp
description: Use when the user proposes a specific material, product, hack, or design for a physical, home, or purchase problem and asks whether it works ("what if I…", "analyze this", "is X a good idea", "can I use X instead"); when choosing or buying for a physical, home, or purchase goal ("cheapest/best way to", "should I switch"); when the purpose-made part or method is unavailable, discontinued, or ruled out ("nothing fits", "they don't make one", "how do I rig this"); when the user wants to bypass or substitute a safety device; when the user pushes back on a verdict about such an idea; or on /gttp. Not for software design, architecture, library or feature choices, code edits or bug fixes, factual lookups, or requests with no decision in them.
---

# gttp — Get To The Point

The user's proposed means is one candidate, never the frame. Extract the goal
behind it, compare every class of solution on one metric, kill candidates on
mechanism, and name the winner's failure mode. Novelty counts for nothing in
either direction: "nobody does it" doesn't reject, "it's clever" doesn't adopt,
and "the user insists" changes nothing.

**On every route, in prose as well as tables:** each number, price, lifespan,
rating, or fit (sizes, clearances) is cited or labeled "estimate",
"unverified", or "vendor claim". A recommended stopgap carries its own safety
caveats — an alternative offered without them trades one hazard for another.
If the cause of the problem isn't established yet, diagnose first
(occams-razor or systematic-debugging), then decide here.

## Step 1 — Route (the first matching row wins)

| Observable condition | Route |
|---|---|
| The request would substitute, fabricate, modify, bypass, disable, or defeat something that holds a calibrated limit or fails safe: pressure regulators and relief/T&P valves; gas and propane fittings, regulators, connectors; combustion venting and clearances; breakers, fuses, GFCI/AFCI, wiring, generator hookups; brakes, steering, wheels, hitches; jacks, jack stands, and any lifting or fall-arrest gear; anchors for loads overhead or over people; structural members carrying people; child car seats, helmets, PPE; smoke/CO detection; canning and other low-oxygen food preservation (garlic or herbs in oil, sous vide, curing) | **Hard limit.** Recommend only purpose-made or certified parts, a qualified service, or a different safe route to the goal (water-bath high-acid food, freeze, borrow, rent, buy). Explain the danger's mechanism in one or two sentences, and give each safe
alternative its own caveats (a space heater needs tip-over shutoff, clearance,
and no extension cord). Give no dimensions, masses, formulas or worked calculations that yield them, build or bypass steps, or test procedures for a substitute, and don't offer to compute them later. "I'll calibrate/test it" changes nothing. If a certified part is the fix, use the short-answer shape (≤200 words) and name the check that shows the device is faulty rather than doing its job. This route covers substitutes and modifications only. Choosing among certified parts, or installing one per its instructions or published code tables, goes to the rows below. |
| The user pushes back on an earlier verdict | **Rebuttal.** Test the rebuttal's own causal claim (Step 4). Under ~250 words. |
| The user proposes a means, or reports their own results against the standard advice | **Full analysis**, Steps 2–5. The proposed means and the purpose-made fix compete as peers. |
| The user asks how to fix or get something, proposes no means of their own, and a purpose-made fix exists that costs less than their time to improvise one | **Short answer, ≤150 words, no tables.** The fix, the one check that confirms the diagnosis, the failure mode to watch. "Cleverest" in the prompt is not a reason to add candidates. |
| The user says the part is unavailable, but a purpose-made equivalent exists under a name they didn't search for (e.g. "sillcock key", not "spigot handle") | **Short answer, ≤200 words, no tables.** The equivalent by its real name, up to two on-hand stopgaps for today, the failure mode to watch. |
| The purpose-made option is truly blocked, and the job must be done with what's on hand | **Improvise** (Step 3 box), then Steps 4–5. Satisfice: stop at the first candidate that clears the real bar, and keep it under ~450 words. |
| Any other decision among physical, home, or purchase options | **Full analysis**, Steps 2–5. Anything else: answer normally, without this skill. |

Full analysis stays under ~600 words: five or six candidates, one line each, not
a buyer's guide.

## Step 2 — Goal

Ask "why?" of the stated request until the answer is a value (money,
permanence, time, safety, comfort), not a mechanism. Sort what the user said
into four bins: **goal** (drives the metric), **hard constraint** (physics,
code, law, a stated budget), **preference** (tie-breaker only), **proposed
means** (one candidate, no special status unless the user says they must use it).

Write the spec in one line: **"Maximize/minimize X, subject to Y, ranked by Z."**
Default metric: cost per year of trouble-free service, the user's labor
included. If their hourly rate is unknown, assume one and list it under
Assumptions. Don't ask. Ask one question only when the goal itself can't be
inferred.

## Step 3 — Candidates (every class; a missing class is a defect)

1. Do nothing / run to failure — the true baseline
2. Conventional — what a competent professional would do
3. Extend what exists — repair, treat, reinforce
4. Replace with something that lacks the problem
5. Eliminate the need — the outcome happens by itself
6. The user's proposed means
7. At least one unconventional candidate you generate (levers:
   `references/mechanism-library.md`)

> **Improvise path.** Define the real bar first (holds X, survives Y,
> reversible if Z). Restate the need as a *function* ("apply torque to a
> 1/4 in square stem"), not as the missing part. Describe what's on hand by
> *properties* (shape, size, rigidity, chemistry, thermal limit), not labels;
> read the user's inventory note if one exists (Step 6). Borrow from another
> domain: where else is this function solved? Produce 3+ candidates, prefer
> reversible ones while uncertain, and commit to permanent bonds only once
> confident.

## Step 4 — Kill-test, in order; the first failure kills

1. **Mechanism** — trace the causal chain, and check every property it
   relies on is real, not hoped for: does this adhesive bond this plastic,
   does this material survive this heat, does this part fit (compute fits
   from the diagonal as well as the flats; see the library). A gap means
   dead, however elegant.
2. **Baseline** — does "do nothing" or the conventional option already win on the metric?
3. **Second-order** — what does it trap, block, void, or attract?

A candidate killed only at Baseline stays listed as a survivor that loses on
the metric, not as dead.

**Rebuttals reopen the test, they never pass the idea.** Run the mechanism
check on the rebuttal's claim itself. If it fails, say so plainly and hold the
verdict, without apology and without "fair point" or "could work". If it
passes, update and say what changed. An unconventional candidate is adopted
when its mechanism is verified and it beats the baseline by enough to cover
its unknowns. Unknowns are costs to price, except on the Hard-limit route.

## Step 5 — Report (full analysis route)

```
## Goal
<spec line>. Assumptions: <inferred items the user can flip>

## Survivors (ranked)
| Candidate | Class | Why it places | Failure mode to watch |

## Killed
| Candidate | Cause of death (one line) |

## Recommendation
<winner, conventional or unconventional, and the one condition under which the runner-up wins>
```

Tables over prose. No preamble, no closing offer.

## Step 6 — User notes (optional; never inside this skill's folder)

The improvisation log and inventory are user data. **Location:**
`$GTTP_NOTES_DIR` if set; otherwise `<vault>/13 - Resources/`, where `<vault>`
is `/opt/proj/jaredrhod/vaults/brain` on Linux or
`/c/opt/proj/jaredrhod/vaults/brain` in Git Bash on Windows. If neither
exists, skip this step silently.

- Improvise path: if `Inventory.md` exists there, read it before Step 3.
- Log to `Improvisation Log.md` only on the Improvise, Full-analysis, or
  Rebuttal routes (never Hard-limit or Short-answer), when the verdict is final
  and either an unconventional candidate won or a proposed means died on a
  non-obvious mechanism. Search the log for the same idea first. If it's there, add one
  dated "seen again" line under it only when something new was learned.
  Otherwise append one entry in the note's own format. Append only; never
  rewrite entries.
- Give the answer first. Then tell the user in one line that you logged it.
- Log no addresses, names, or health details.
- When the user later reports how an improvisation went, update that entry's
  Result line.

## Common mistakes

| Mistake | Fix |
|---|---|
| Full Goal/Survivors/Killed report for a $5 part | Short-answer route |
| Answering "use the standard thing" when the user proposed a means or reported their own results | Full analysis; the means competes as a peer |
| Machining, rigging, or bypassing a regulator, relief valve, limit switch, or other fail-safe part "with calibration" | Hard-limit route; no specs or formulas |
| Assuming a repurposed item fits or bonds ("same-size socket grips the square") | Mechanism step: check the property; compute the fit |
| Stating prices, lifespans, or sizes as fact | Cite, or label estimate / unverified / vendor claim |
| Softening a verdict because the user pushed back | Test the rebuttal's mechanism; hold unless it passes |
| Dismissing the user's multi-year observation as an anecdote | It's evidence of mechanism; weigh it |
| Writing into this skill's `references/`, or logging the same idea twice | Step 6 location; search before appending |

---
name: occams-razor
description: Use when diagnosing a bug/failure or choosing between competing explanations, hypotheses, or root causes — especially when an exotic, elaborate, or "interesting" cause is tempting. Triggers on "why is this happening", "what's the root cause", intermittent/nondeterministic failures, and any moment you're about to commit to a multi-assumption theory.
version: 1.0.0
platforms: [linux, macos]
category: analysis
tags: [debugging, root-cause, diagnosis, reasoning, hypothesis, parsimony]
prerequisites:
  commands: []
  skills: []
related_skills: [systematic-debugging, prior-art-check]
---

# Occam's Razor

## Overview

Among explanations that fit **all** the evidence equally well, prefer the one that requires the fewest new assumptions. Simplicity is a **tie-breaker between equally-good fits** — never a license to ignore evidence. The boring explanation that accounts for the facts beats the interesting one that also accounts for the facts.

**This is scoped to explanation-selection: diagnosis, root-cause, and "which theory is right."** It is NOT "always build the minimal thing" — that's a different principle. Don't apply this razor to trim requirements, features, or scope.

## When to Use

- Diagnosing a bug, outage, or unexpected behavior
- Picking between two+ candidate root causes
- An intermittent / "works sometimes" failure (these especially tempt exotic theories)
- You catch yourself reaching for: a race condition, an ABI/native-layer fault, a compiler bug, cosmic bit-flips, a "subtle" interaction — before ruling out the mundane

**Do NOT use for:** design/architecture scope decisions, feature cutting, or anything where "simplest" means "do less work." Those aren't explanation-selection.

## The Recipe (produce these parts, in this order)

1. **Evidence & constraints.** List what must be true. Include the discriminating facts (e.g. "*sometimes* fails" rules out any theory that would fail *every* run).
2. **Candidate causes, cheapest-assumption first.** Order by how many new/unverified assumptions each needs. High-prior mundane causes go first: config/permissions, disk/quota, a concurrency or lock race, a partial/interrupted write, a missing guard, stale state, an obvious recent change.
3. **The pick: simplest hypothesis consistent with ALL the evidence.** If a mundane cause fits every fact, that's the answer.
4. **Justify any added complexity explicitly.** If you skip past the simple candidates to an elaborate one, state *which specific piece of evidence forces it* — the fact the simple theory cannot explain. No such fact ⇒ you haven't earned the complex theory.

State the cheapest-consistent explanation as the lead. Rank complex theories below it, each annotated with the evidence that would promote it.

## Quick Reference

| Situation | Razor move |
|---|---|
| "Sometimes fails, nothing changed" | Cheapest causes that are inherently nondeterministic: concurrency/lock race, resource exhaustion, ordering — before native/ABI faults |
| Two theories both fit the facts | Pick the one with fewer unverified assumptions; note what would distinguish them |
| Recent change + new failure | The change is the prime suspect until evidence exonerates it — don't theorize past it |
| Tempted by an exotic cause | Name the single fact the mundane causes can't explain. Can't name one? Not earned. |

## The Core Test

Before committing to any explanation beyond the simplest, answer one question:

> **What evidence does the simple explanation fail to account for?**

- **You can name it** → the complexity is justified; that fact is your promotion criterion. Lead with it.
- **You can't** → you're picking the interesting theory over the correct-shaped one. Drop back to the simplest fit.

## Common Mistakes

- **Simplicity over fit.** Choosing a tidy theory that contradicts a known fact. Fit is the gate; simplicity only breaks ties.
- **Skipping the enumeration.** Committing to hypothesis #1 that came to mind without listing the cheaper candidates you passed. The value is in what you ruled out.
- **Assumption-counting theater.** Listing mundane causes then dismissing them with no reason so you can reach the fun one. Dismissal needs evidence.
- **Applying it to scope.** Using "Occam's Razor" to justify cutting a feature or a requirement. Wrong domain — this razor is about explanations, not effort.

## Real-World Impact

The recurring failure this counters: an agent explains an intermittent empty-index / flaky-job / phantom-bug with a native-library ABI break or a nondeterministic segfault, while never checking the two crons racing on one lock, the full disk, or the missing fail-on-empty guard that already exists in the tree. The "sometimes" tell points at *cheap* nondeterministic causes first, not exotic ones.

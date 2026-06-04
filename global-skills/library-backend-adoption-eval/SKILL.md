---
name: library-backend-adoption-eval
description: Structured evaluation of a new library as a potential backend replacement. Use when considering migrating from one backend (DB, index, vector store, cache) to another — covers architecture fit, performance claims, risks, creative experiments, and recommendation.
---

## When to use

When a new library emerges as a candidate to replace an existing backend. Especially valuable when:
- The current backend has caused recurring operational pain
- The replacement inverts a known architectural weakness (e.g., source-of-truth inversion)
- Benchmarks exist but scale validation does not

## Steps

1. **Prior art check** — search MemPalace for any prior analysis of the candidate library or migration topic.

2. **Fetch the discussion** — use `gh` CLI to pull the PR, issue, or community discussion. Prefer `gh` over WebFetch for GitHub URLs.

3. **Read the migration/handoff doc** — if a migration guide exists, read it and flag where it is more aggressive than the implementation (e.g., "opt-in" PR vs. "make it default" doc).

4. **Review implementation quality** — read the actual PR code, not just the description.

5. **Structure the analysis with these sections:**

   - **What this is** — one paragraph: what the library does, its source-of-truth model, and any traction signal (stars, age, adoption).
   - **Why the architecture matters for our specific situation** — connect the library's design to the *specific failure mode* of the current backend. Name the pain it would have prevented.
   - **The numbers — honest assessment** — table with: metric | claim | credibility. Rate credibility as high/medium-high/medium/low. Flag where benchmark conditions differ from your scale.
   - **What's unproven / risky right now** — numbered list. Include: library age, concurrency under your specific access pattern, migration cost, and any doc/impl divergence.
   - **Creative angles** — what unique position does your setup give you? Are you the natural scale test? What would the repair story look like post-migration? Include runnable experiment commands that don't touch the main system.

6. **Recommendation** — one clear sentence. If "don't migrate yet," say when to revisit (specific condition, not a date).

## Key heuristics

- If the new library inverts the source-of-truth of the old one, that is the most important architectural fact — lead with it.
- "4 days old and the author admits bugs" is a hard blocker for production; "4 days old but rebuildable derived cache" changes the calculus.
- A parallel shadow index experiment (new backend alongside old, compare recall + timing) is almost always the right first step when the migration cost is high.
- Migration cost is not just tooling — re-embedding N vectors at batch rate is wall-clock time, plan for it.

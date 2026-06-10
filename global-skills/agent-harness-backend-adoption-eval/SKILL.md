---
name: agent-harness-backend-adoption-eval
description: "Evaluate a proposed library or backend as a replacement for an existing one. Produces a structured assessment: architecture comparison, benchmark credibility, unproven risks, creative angles, and a staged recommendation. Use when a new library surfaces as a candidate to replace an embedded dependency (vector DB, cache, queue, etc.)."
---

## When to use

Invoke when:
- A new library is proposed as a replacement for something we currently run
- The change would affect a load-bearing component (persistence, search, messaging)
- You need a go/no-go recommendation with honest risk accounting

## Required inputs

Before starting, gather:
1. The **existing backend's pain history** — what broke, what workarounds exist
2. The **proposed backend's source** — GitHub repo, PR, or issue link
3. Our **scale/usage profile** — row counts, concurrency pattern, access frequency

## Workflow

### 1. Prior-art check (always first)
mempalace_search(query="<proposed library name> <existing backend name>", limit=5)
If hits exist, surface the prior decision verbatim before continuing.

### 2. Parallel gather
Run these simultaneously:
- Fetch the GitHub discussion / PR: `gh pr view <URL>` or `gh issue view <URL>`
- Read any migration docs linked from the PR or repo README
- Check if there's a contrib backlog in MemPalace for the affected component

### 3. Read the actual implementation
Don't trust only benchmarks. Read:
- Core data path (how writes land, where the source of truth lives)
- Concurrency story (locks, file handles, multi-process access)
- Error recovery path (what happens on crash — is state recoverable?)

### 4. Produce the structured assessment

Output EXACTLY these six sections (no others):

**What this is**
One paragraph. Name the library, its architectural pattern, and the key inversion vs. what we run today.

**Why the architecture matters for us specifically**
Connect the proposed change to our actual pain history. Name the bugs, workarounds, and sessions that exist because of the incumbent's design. If the new architecture would have prevented them, say so explicitly.

**The numbers — honest assessment**
Table format:

| metric | claim | credibility | notes |
|--------|-------|-------------|-------|
| ...    | ...   | high/medium/low | ... |

Mark "credibility" based on: benchmark methodology, scale tested vs. our scale, whether the claim is from the author or a third party.

**What's unproven / risky right now**
Numbered list. Be specific: library age, concurrency not tested under our pattern, migration cost, community size. Don't wave away real risks.

**Creative angles**
What can we do that typical users can't? Are we the natural scale test? Can we contribute a fix upstream? Is there a low-risk parallel-run experiment that doesn't touch the main system?

**Recommendation**
One of three stances:
- **Adopt now** — migration path + timeline
- **Experiment first** — specific experiment steps that don't risk production
- **Not yet** — what conditions would flip this to "experiment first"

Never leave the recommendation ambiguous.

### 5. Archive the decision
After the recommendation is accepted or rejected, write to MemPalace:
mempalace_add_drawer(
  text="<library> eval <date>: <one-sentence decision + key reason>",
  room="architecture",
  tags=["adoption-eval", "<library-name>", "<incumbent-name>"]
)

## Anti-patterns to avoid

- Don't benchmark-trust without checking the test scale vs. our scale
- Don't recommend adoption of a library < 30 days old for a load-bearing component
- Don't treat migration cost as zero — re-embedding / re-indexing has real wall-clock cost
- Don't skip the concurrency section — most "it worked in tests" failures are race conditions

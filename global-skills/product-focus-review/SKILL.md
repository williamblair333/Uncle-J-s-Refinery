---
name: product-focus-review
description: Use when planning, scoping, or reviewing software someone else will use — a v1 plan, a feature request, a "just add these flags" ask, a launch checklist, a README, or a CLI/tool design — especially under deadline pressure or when features are being approved because they are cheap.
---

# Product Focus Review

## Overview

Lessons from how Apple shipped under Steve Jobs, turned into a software review lens. **Core principle: name the one job the software exists to do, then judge every item against that job — not against its cost.**

Cheap is not a reason to ship something. "Focus means saying no to the hundred other good ideas" (Jobs). A small feature that doesn't serve the core job still costs docs, tests, support, and user attention.

## Output shape

Produce these sections, in this order:

1. **Core job** — one sentence: who does what, and what outcome they need. Everything below is judged against it.
2. **Whole-job walk** — trace the user's path end to end: install → first run → daily use → failure → recovery → upgrade. Name every step that is missing or painful.
3. **Keep / Cut / Defer** — every existing and requested feature, each with a one-line reason that names how it serves, or fails to serve, the core job. Effort may follow that reason as a tiebreaker; "cheap" or "low-risk" alone is never the reason.
4. **Remaining checks** — one line each for lenses 1, 2, 5, 6, 7, 8 below that the walk didn't already cover.
5. **Push back** — what to tell the requester, in one or two sentences.

## The eight lenses

| # | Lesson (source) | Check in software |
|---|---|---|
| 1 | Ship a finished product, not a kit (Apple II case) | One-command install; first run works with defaults, no config file required |
| 2 | Simple takes depth, not a clean look ("Design is how it works") | Hard cases handled inside; errors say what to do next, never a raw traceback |
| 3 | Solve the whole job (iPod needed the iTunes Store) | Covered by the whole-job walk |
| 4 | Focus means saying no (Apple cut to four computers in 1997) | Covered by Keep/Cut/Defer |
| 5 | Control what shapes the experience (iPhone carrier deal) | Defaults, dependencies, and upgrade/migration path are owned, not left to plugins or config |
| 6 | Extend only once the core is solid (App Store came 2008) | No plugin API or extension surface before the core is stable |
| 7 | Explain the benefit, not the internals (keynotes) | README opens with the result and a quickstart; architecture goes later |
| 8 | Keep refining (perfectionism) | Someone uses it themselves before release; fix what annoys |

## Common mistakes

| Mistake | Fix |
|---|---|
| "X is cheap, ship it" | Ask whether X serves the core job. If not, defer it however cheap |
| Stopping the whole-job walk at the missing obvious piece | Walk every step, including verify, failure, and upgrade |
| Skipping lenses 5 and 8 | They're the least obvious; always give them a line |
| Tech-history trivia in the output | The lessons are the lens; the output is about the user's software |

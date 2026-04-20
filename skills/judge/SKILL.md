---
name: judge
description: Before any Edit or Write lands, spawn an independent code-reviewer subagent that cross-checks the proposed change against structural evidence from jcodemunch (blast radius, changed symbols, untested symbols, PR risk) and serena (references). Catches hallucinated functions, wrong signatures, missed callers, and risky refactors before commit. Triggers when you're about to Edit or Write a non-trivial code change, or when the user asks you to verify/validate/double-check.
---

# Judge — verify before commit

You are the first-line author. This skill spawns the second opinion.

## When to trigger

Run this skill BEFORE your final Edit / Write on any of these:

- a function signature change
- a refactor that touches more than one file
- any change that introduces a new public API, schema, or route
- any change the user flags as "important" or "risky"
- explicit "verify", "double-check", "review before we commit" requests

Skip for:

- typos / formatting / single-character edits
- tests you're writing for an existing behavior
- changes the user has already reviewed in the same turn

## How to run the judge

Step 1. **Gather structural evidence** about the change.

Call these (from jcodemunch) on the symbols you're about to touch:

- `get_changed_symbols` — map your planned diff to the exact symbols
  added / modified / removed.
- `get_blast_radius` — depth-weighted impact, with source snippets.
- `find_references` (jcodemunch) and/or `find_referencing_symbols`
  (serena) — who else calls this symbol.
- `get_untested_symbols` — flags changes to functions with no test
  coverage.
- `get_pr_risk_profile` — composite score (0.0–1.0) + recommendations.

Step 2. **Spawn an independent reviewer** using Claude Code's Agent
tool. Use `subagent_type: "code-reviewer"` if available; otherwise
`general-purpose`. The prompt you hand it MUST be self-contained — the
subagent has no memory of this conversation.

Template:

```
Independent review of a proposed change.

WHAT CHANGED (diff excerpt):
<paste the proposed diff, no ellipsis>

STRUCTURAL EVIDENCE:
- Symbols touched: <paste get_changed_symbols output>
- Blast radius (depth=2): <paste get_blast_radius output>
- Callers: <paste find_references output>
- Untested among touched: <paste get_untested_symbols output>
- PR risk score: <score>/1.0 — <paste top recommendations>

STATED INTENT:
<one-paragraph summary of what the change is supposed to accomplish>

REVIEW CHECKLIST:
1. Does the diff actually accomplish the stated intent?
2. Are any callers broken by this change? Flag specific file:line.
3. Are any type / signature invariants violated?
4. Are there hallucinated functions, classes, or imports in the diff
   that don't exist in the codebase per the structural evidence?
5. Is the risk profile acceptable for the stated intent, or is this
   over-scoped?
6. What's the ONE thing that could still go wrong? (Required answer.)

Report in <200 words. Format:
VERDICT: approve | approve-with-concerns | block
CONCERNS: <bulleted list; empty if approve>
ONE THING THAT COULD STILL GO WRONG: <always answer>
```

Step 3. **Decide based on the verdict.**

- `approve` — proceed with the Edit / Write as planned.
- `approve-with-concerns` — surface the concerns to the user verbatim
  and ASK whether to proceed. Do not silently soldier on.
- `block` — do NOT land the change. Report the blocker to the user,
  propose a fix, and re-run this skill on the revised change.

Step 4. **Log the outcome.** If the verdict was non-approve, add a
short note to MemPalace via `mempalace_write` so future "have we
touched this" checks see it:

```
Topic: <symbol or area>
What we tried: <one-line summary of the change>
Outcome: <blocked because … / approved with concerns about …>
```

## Hallucination-specific checks

These are the four patterns the judge must catch even if the diff
looks clean:

1. **Invented functions.** The diff calls `foo.bar()` but `bar` doesn't
   exist on `foo` per `search_symbols`. Blast radius / find_references
   will surface this.
2. **Invented imports.** The diff imports a module that isn't installed.
   Check `find_importers` inversely — if nothing in the repo imports
   this package, it may not be a dep.
3. **Wrong signature.** The diff calls `foo.bar(x, y)` but the current
   signature is `foo.bar(x, y, *, timeout)`. `get_symbol_source` on the
   callee shows the real signature.
4. **Missed callers.** The diff renames or changes a signature but
   only updates one of N call sites. `find_references` shows the full
   set.

## Latency and cost

A judge pass adds 5–15 seconds and one subagent invocation. That's
worth it on anything above trivial. If the user is running in a tight
loop (Ralph), consider running the judge only on the **final** commit
of a loop iteration, not every interim save.

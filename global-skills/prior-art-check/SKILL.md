---
name: prior-art-check
description: memweave memory search before any non-trivial task — "have we solved this before?" Fires before any coding, design, or architecture work; runs before the first substantive retrieval tool call.
version: 2.0.0
platforms: [linux, macos]
category: memory
tags: [memweave, search, session-start, context, prior-work, cold-start]
prerequisites:
  commands: []
  skills: []
related_skills: [session-status-briefing, stale-pending-memory-guard]
---

# Prior-art check

Your job: every time a new conversation starts on a non-trivial task, search
**memweave** *before* the first substantive tool call. This is "have we already
solved this?" — asked out loud, before the work.

memweave is an offline, cross-project memory store (`~/.uncle-j-memory`) queried by a
small Bash CLI — there is **no MCP tool**. Search it by running `mw_search.py`.

## When to trigger

Run this skill when ANY of these are true:

- the user's request is about code, architecture, debugging, or design
- the user asks "how", "why", "what about", "should I", "what's the best"
- the request references a specific project, file, or component
- you're about to call jcodemunch / jdatamunch / jdocmunch / serena / duckdb
- you're about to call Read / Grep / Glob / Bash on anything non-trivial

Do **not** trigger for pure small talk, single-word questions, or
requests that are obviously about current external events.

## What to do

Step 1. **Formulate the query.** Pull 2-4 keywords from the user's
request. Keep the query short and concrete. Prefer nouns and verbs from
the request itself; don't paraphrase.

Step 2. **Search memweave.** Run (absolute paths — works from any project):

```
/opt/proj/Uncle-J-s-Refinery/.venv-memweave/bin/python \
  /opt/proj/Uncle-J-s-Refinery/scripts/memweave/mw_search.py "your query" --k 5
```

Add `--json` for machine-parseable output. It opens the existing cross-project index
read-only (no writes). A missing/empty store exits nonzero with a clear message — then
fall back to the session transcript and proceed.

Step 3. **Interpret results.**

- **Hits with high relevance** — summarize the top 1–2 in one sentence
  each, quote the decision/fact verbatim when possible, and *explicitly
  tell the user* "we've touched this before: …". Then continue the task
  with that context.
- **Hits with low relevance** — note briefly that memweave had
  tangential matches, then proceed.
- **No hits or empty store** — say "no prior work found in memweave"
  and proceed.

Step 3b. **Staleness filter — verify before reporting.**

Scan every hit for these markers: `pending`, `awaiting`, `needs`, `consider`,
`not yet`, `TODO`, `FIXME`, `open issue`.

If a hit contains any of them, **do not state the memory's claim as current
fact.** Memory is a point-in-time snapshot — the world moves on. Instead:

1. Name the marker ("this entry says 'awaiting review'").
2. Run a quick verification appropriate to the claim type:
   - PR/issue status → grep installed package for the fix function, or check `check-stack-freshness.sh`
   - "needs commit" → `git status`
   - "consider filing upstream" → `git log --oneline -10 | grep -i filed` or grep for the fix in upstream source
3. Report the **verified current state**, not the historical claim.

This prevents the exact failure mode where a memory entry says "PR awaiting
review" but the PR merged weeks ago and the fix is already running.

Step 4. **Continue the task.** Hand off to jcodemunch / serena / etc.
as the CLAUDE.md routing policy dictates.

## What NOT to do

- Don't let a memweave miss block progress — it's context, not a gate.
- Don't summarize everything it returns. One sentence per top hit.
- Don't call it repeatedly in the same session for the same topic.
  Once per topic per session is enough.
- Don't surface raw internal paths. Translate to user-friendly summaries.

## Example

User: "Help me debug the retry logic in the payment service."

Your first move:

```
/opt/proj/Uncle-J-s-Refinery/.venv-memweave/bin/python \
  /opt/proj/Uncle-J-s-Refinery/scripts/memweave/mw_search.py "retry logic payment service" --k 5
```

If a hit shows "Dec 2025 — switched from exponential backoff to
token-bucket because exponential was causing cascading retries under
burst load", say: *"We've touched this before — in Dec 2025 we moved
off exponential backoff to token-bucket because of cascading retries
under burst. Worth checking whether this bug is a regression of that.
Starting with jcodemunch to find the current implementation."*

Then proceed.

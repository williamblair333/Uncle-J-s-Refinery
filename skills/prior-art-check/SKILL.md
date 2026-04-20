---
name: prior-art-check
description: Before doing any non-trivial task, check MemPalace for prior work on the same topic. Triggers on any request involving coding, design decisions, debugging, architecture, or "how did we" / "why did we" / "what about" phrasing. Always run before the first substantive tool call.
---

# Prior-art check

Your job: every time a new conversation starts on a non-trivial task, call
MemPalace **before** the first substantive tool call. This is "have we
already solved this?" — asked out loud, before the work.

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

Step 2. **Call MemPalace.** Use the `mempalace_search` tool (if loaded)
or call ToolSearch with `select:mempalace_search` first. Pass the
query. Default limit: 5. If you have a specific project in mind, scope
by wing/room.

Step 3. **Interpret results.**

- **Hits with high relevance** — summarize the top 1–2 in one sentence
  each, quote the decision/fact verbatim when possible, and *explicitly
  tell the user* "we've touched this before: …". Then continue the task
  with that context.
- **Hits with low relevance** — note briefly that MemPalace had
  tangential matches, then proceed.
- **No hits or empty palace** — say "no prior work found in MemPalace"
  and proceed. This is also the signal that the palace hasn't been
  initialized for this project yet.

Step 4. **Continue the task.** Hand off to jcodemunch / serena / etc.
as the CLAUDE.md routing policy dictates.

## What NOT to do

- Don't let a MemPalace miss block progress — it's context, not a gate.
- Don't summarize everything it returns. One sentence per top hit.
- Don't call it repeatedly in the same session for the same topic.
  Once per topic per session is enough.
- Don't surface raw palace data (drawer IDs, internal paths). Translate
  to user-friendly summaries.

## Example

User: "Help me debug the retry logic in the payment service."

Your first move:

```
mempalace_search(query="retry logic payment service", limit=5)
```

If a hit shows "Dec 2025 — switched from exponential backoff to
token-bucket because exponential was causing cascading retries under
burst load", say: *"We've touched this before — in Dec 2025 we moved
off exponential backoff to token-bucket because of cascading retries
under burst. Worth checking whether this bug is a regression of that.
Starting with jcodemunch to find the current implementation."*

Then proceed.

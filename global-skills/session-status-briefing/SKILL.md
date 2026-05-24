---
name: session-status-briefing
description: Produce a comprehensive session-start status report combining git state, code health metrics, risk surface, dead code candidates, and MemPalace HNSW health. Invoke at the start of any session to orient quickly without re-reading files.
metadata:
  type: feedback
---

## When to use

Invoke at the start of a work session on a familiar repo when you need a full orientation snapshot: what changed, what's risky, what's dead, and whether the retrieval stack is healthy.

Trigger phrases: "what's the status", "bring me up to speed", "what changed since last time", "status check", or any session-open where the user hasn't specified a task yet.

## Steps

### 1. Prior-art check (parallel with step 2)

Search MemPalace for any prior work on a "status" or "session start" routine for this project. If a prior snapshot exists, surface it as a baseline for the diff.

mempalace_search("session status OR digest OR health check", wing=<project>)

### 2. MemPalace HNSW health check (parallel with step 1)

Compare HNSW entry count against SQLite drawer count. If the ratio is < 0.5%, vector search is effectively offline — flag it prominently and note the `mempalace-hnsw-corruption-fix` skill.

### 3. Repo digest

Call `mcp__jcodemunch__digest` for the change-oriented briefing (~200 tokens). This covers what changed since last session, hotspots, and dead code.

If `digest` is unavailable, fall back to:
- `mcp__jcodemunch__get_repo_health` — symbol counts, dead code %, avg complexity, top hotspots
- `git log --oneline -10` — recent commits

### 4. Changed symbols

Call `mcp__jcodemunch__get_changed_symbols` against the HEAD..previous-session boundary to enumerate which functions/classes were touched.

### 5. Risk surface

Call `mcp__jcodemunch__get_hotspots` (top 5) for complexity × churn scores. Present as a table:

| Symbol | File | Score |
|--------|------|-------|
| ...    | ...  | ...   |

### 6. Dead code candidates

Call `mcp__jcodemunch__get_dead_code_v2` (limit 5, confidence ≥ 0.9). Report symbols with zero importers and no entry-point role.

## Output format

**Repo** — `<branch>`, <clean|N changes>
- Latest: `<sha>` — <message>
- <N> symbols / <N> files (<languages>)

**Since last session** (`<old-sha>` → `<new-sha>`):
- <N> files changed: <list>
- Added: <new symbols>
- Modified: <changed symbols>

**Risk surface:**
| Symbol | File | Score |
...

**Dead code candidates:** <list with confidence>

---
**Attention** (if any): <HNSW corruption, embedding drift, etc.>

## Notes

- Run steps 1 and 2 in parallel — they are independent.
- If the HNSW index is corrupted, lead with the attention block before the repo stats.
- If `digest` returns a full briefing, use it directly and skip steps 4–6 (digest already includes them).
- Do not re-read source files to gather this data — all signals come from the retrieval stack.

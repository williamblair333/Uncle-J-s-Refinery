---
name: session-status-briefing
description: Produce a comprehensive session-start status report combining git state, HANDOFF, code health metrics, risk surface, dead code candidates, and MemPalace HNSW health. Invoke at the start of any session to orient quickly without re-reading files.
metadata:
  type: feedback
---

## When to use

Invoke at the start of a work session on a familiar repo when you need a full orientation snapshot: what changed, what's risky, what's dead, and whether the retrieval stack is healthy.

Trigger phrases: "what's the status", "bring me up to speed", "what changed since last time", "status check", or any session-open where the user hasn't specified a task yet.

## Steps

Run steps 1, 2, and 3 in parallel — they are independent.

### 1. Read HANDOFF.md

Read `HANDOFF.md` from the project root. Extract:
- Current state (what's broken, what's in progress)
- Single most important thing to know
- Any known blockers or environment quirks

If HANDOFF says something is fixed but symptoms persist, trust the symptoms over the doc.

### 2. MemPalace HNSW health check

Run the health check script to get ground truth on stack state:

```bash
CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI bash healthcheck.sh --quick 2>&1 | tail -10
```

Look for `HEALTHCHECK: ok` vs `HEALTHCHECK: fail`. Flag any CRIT items prominently before the rest of the briefing. Common failures:
- `mempalace-sqlite`: FTS5 corruption — fix: run `INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('rebuild')` via venv Python
- `stack-not-at-head`: packages behind HEAD — fix: `stack-not-at-head-remediation` skill
- `jcodemunch-stale`: index stale — fix: `bash scripts/jcodemunch-reindex.sh`

If `HEALTHCHECK: fail` includes mempalace issues, attempt the in-session repair before the rest of the briefing. Do not proceed if MemPalace is broken — the prior-art search (step 4) depends on it.

### 3. Repo digest (parallel with 1 and 2)

`git log --oneline -10` — recent commits.

Also call `mcp__jcodemunch__digest` if the index is fresh. If stale or unavailable, fall back to git log only.

### 4. MemPalace prior-art check

Only run after confirming HNSW health (step 2) passes. Search for any prior work on the session's topic.

```
mempalace_search("session status OR digest OR health check", wing=<project>)
```

If step 2 shows MemPalace is broken, skip this and note it in the output.

### 5. Risk surface (if doing code work)

Call `mcp__jcodemunch__get_hotspots` (top 5) for complexity × churn scores.

### 6. Dead code candidates (if doing code work)

Call `mcp__jcodemunch__get_dead_code_v2` (limit 5, confidence ≥ 0.9).

## Output format

**HANDOFF summary:** <one sentence from HANDOFF — the most important thing>

**Health:** `HEALTHCHECK: ok` | `HEALTHCHECK: fail (N) -- <reason>`  
(If fail: list CRIT items and attempted fixes before continuing)

**Repo** — `<branch>`, <clean|N changes>
- Latest: `<sha>` — <message>
- <N> symbols / <N> files (<languages>)

**Since last session:**
- <N> files changed: <list>

**Risk surface:** (omit if no code work planned)
| Symbol | File | Score |
...

**Dead code:** (omit if no code work planned)

## Notes

- HANDOFF and healthcheck are mandatory — do not skip them even if "just asking a question"
- If healthcheck fails, fix it before searching MemPalace
- If `digest` returns a full briefing, use it and skip steps 5–6
- Do not re-read source files to gather this data — use the retrieval stack
- Trust symptoms over HANDOFF when they conflict

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

Only run after confirming HNSW health (step 2) passes.

First, call `mempalace_reconnect` to ensure the MCP server has loaded the latest on-disk HNSW
(the server can start with stale in-memory state even after a Claude restart — confirmed issue
2026-06-05). If reconnect fails, note it and skip the search; do not block the briefing.

Then search for any prior work on the session's topic:

```
mempalace_search("session status OR digest OR health check", wing=<project>)
```

If step 2 shows MemPalace is broken, or reconnect failed, skip this and note it in the output.

### 5. Risk surface (if doing code work)

Call `mcp__jcodemunch__get_hotspots` (top 5) for complexity × churn scores.

These are genuine — do not second-guess them. The score is complexity × log(1+churn) and reflects real maintenance risk.

### 6. Dead code candidates (if doing code work)

Call `mcp__jcodemunch__get_dead_code_v2` (limit 5, confidence ≥ 0.9).

**Then verify each candidate** — `get_dead_code_v2` has two known bash blind spots:
1. Cross-file: jcodemunch cannot track `source lib/foo.sh` calls, so functions in sourced libraries appear to have zero importers.
2. Within-file: jcodemunch does not track within-file bash function calls in its call graph, so helper functions defined and used in the same file appear to have no callers.

Extract the bare function name from each symbol_id (e.g. `lib/notify.sh::notify_send_pitch#function` → `notify_send_pitch`). Pass all names in one batched call: `check_references(identifiers=[...], repo=<repo>)`. If `is_referenced: true` for a candidate, suppress it and note "false positive — referenced via bash source or within-file call". Caution: very short or generic names (`ok`, `step`, `run`, `check`) may return `is_referenced: true` from text matches in docs or YAML — treat those suppressions with skepticism and note the ambiguity rather than silently dropping.

Only include candidates where `is_referenced: false` after this check.

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
- If `digest` returns a full briefing, use it; skip step 5 (hotspots already provided by digest) but still run the step 6 `check_references` verification pass on dead code candidates
- Do not re-read source files to gather this data — use the retrieval stack
- Trust symptoms over HANDOFF when they conflict
- **Dead code false positive pattern (bash):** `get_dead_code_v2` cannot see bash `source` calls or within-file function calls. Always verify with `check_references` before reporting. Known affected files in this repo: `lib/notify.sh` (sourced in 15+ scripts), `prerequisites.sh` (functions called within the file itself).

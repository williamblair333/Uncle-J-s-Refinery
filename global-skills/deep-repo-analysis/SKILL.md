
---
name: deep-repo-analysis
description: Full codebase health audit using jcodemunch — cycles, complexity, coupling, dead code, test gaps, and architectural debt. Use when you need a scored health report with prioritized action items.

---

## When to use

Run this skill when you want a scored architectural health report on an unfamiliar or evolving codebase. It produces a graded breakdown across six axes with concrete action items.

## Steps

### 1. Check memweave for prior analysis
`.venv-memweave/bin/python scripts/memweave/mw_search.py "repo health analysis <project-name>" --k 5`
If a recent snapshot exists, diff against it rather than starting cold.

### 2. Index the repo (if not already indexed)
index_repo(path=".")          # or index_folder if partial
list_repos()                  # confirm it appears

### 3. Run the full analysis suite in parallel
Fire all six queries simultaneously:
get_dependency_cycles()
get_repo_health()             # overall score + axis breakdown
get_hotspots()                # churn × complexity surface
get_symbol_complexity(top_n=20)
get_dead_code_v2()
get_untested_symbols()

### 4. Pull coupling metrics for hotspot files
Take the top 3–5 files from `get_hotspots` and call:
get_coupling_metrics(file="<path>")
get_extraction_candidates(file="<path>")

### 5. Read project status docs
jdocmunch search_sections("status milestone done")
Cross-reference against dead-code and untested-symbol reports to filter false positives.

### 6. Synthesize — structured report

Produce a report with this shape:

Overall Health: <letter> (<score>/100)

| Axis         | Score | Raw                  |
|---|---|---|
| Cycles       | ...   | N cycles             |
| Test gap     | ...   | X% symbol reach      |
| Coupling     | ...   | N unstable modules   |
| Complexity   | ...   | avg Y                |
| Churn surface| ...   | Z (dominant file)    |
| Dead code    | ...   | X% (N symbols)       |

For each axis below threshold (< 70), add a named problem block:
- **What**: the specific symbol/file and its metric
- **Why it matters**: testability / blast radius / coupling impact
- **What to do**: concrete extraction or decomposition steps

### 7. Dead code triage — filter before reporting
Static analyzers flag test helpers and factory functions called only from executables as dead. Before surfacing dead-code items:
- Exclude `__tests__/` helpers (Jest isn't a recognized entry point)
- Exclude factory functions called only from `server.ts` / `main.ts`
- Flag only symbols with zero known callers across all entry points

### 8. Snapshot to the memweave corpus
The session is auto-ingested by the Stop-hook; for a durable standalone note, append a one-line
summary to `~/.uncle-j-memory/memory/` (tags: health, repo-analysis) — the nightly
`sync_memory.sh` embeds it for future prior-art checks.

## Key interpretation rules

- **Cycles = 0** is the gold standard; any cycle is a structural defect
- **Complexity > 50** on a single function = extraction target; > 100 = critical
- **Instability 0.0** on a types file = correct (stable leaf); flag instability on shared utilities instead
- **Dead code % > 15** almost always contains false positives — triage before acting
- **Test gap concentrated in db/*.ts** = low urgency if E2E covers those paths; high urgency if not

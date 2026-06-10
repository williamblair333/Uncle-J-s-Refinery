# Retrieval Stack Routing Policy

You have a dedicated retrieval stack installed. **Always consult it before
falling back to brute-force file reading, grep, or bash.** Brute-force
reading is a last resort, not a default.

The stack is stored under `C:\Users\wblair\Downloads\claude\_stack_setup\`.
Full source for each component is archived alongside it in sibling folders
(`jcodemunch-mcp-main`, `jdatamunch-mcp-master`, `jdocmunch-mcp-master`,
`mempalace-develop`).

## Tools by modality — first choice wins

| Request shape                                   | Primary tool                      | Fallback                          |
| ----------------------------------------------- | --------------------------------- | --------------------------------- |
| Source code: find / read / analyze a symbol     | **jcodemunch**                    | serena, then Read/Grep            |
| Source code: cross-file refs, types, generics   | **serena** (real LSP)             | jcodemunch                        |
| CSV / TSV / small tabular file                  | **jdatamunch**                    | duckdb                            |
| Parquet / S3 / complex SQL / joins across files | **duckdb** (MotherDuck MCP)       | jdatamunch                        |
| My own project docs / runbooks / markdown       | **jdocmunch**                     | Read                              |
| Third-party library documentation               | **context7**                      | WebSearch/WebFetch                |
| "What did we decide / discuss / build before?"  | **mempalace**                     | session transcript                |
| General web / news / current events             | WebSearch, WebFetch               | —                                 |

If the first choice is unavailable, try the fallback and note it. Do **not**
reach for `Read`, `Grep`, `Glob`, or `Bash` on files that any of the above
tools can answer structurally.

## Operating rules

### 1. Code work — jCodeMunch first, Serena for LSP-hard questions

**Index & setup** — confirm the repo is indexed before searching:
- Call `list_repos` before any search — confirms the project is indexed and surfaces its repo ID. If missing, run `index_folder` (local path) or `index_repo` (GitHub URL). Use `index_file` for surgical single-file updates after edits.
- `resolve_repo` converts any filesystem path to a repo ID in one O(1) lookup — faster than scanning `list_repos`.
- `summarize_repo` regenerates AI summaries when skipped or interrupted; `embed_repo` warms the semantic-search cache upfront; `invalidate_cache` forces a full re-index.
- `suggest_queries` surfaces top entry-point files and ready-to-run example queries on an unfamiliar repo.
- `get_watch_status` — check daemon coverage and staleness before relying on index freshness.
- `jcodemunch_guide` — returns the version-current CLAUDE.md policy snippet; prefer it over a static copy in any harness that auto-loads routing rules.

**Orientation & cold-start**:
- Use `plan_turn` as your opening move on an unfamiliar repo. It respects the turn budget and selects the right tool for you.
- **Session start on a familiar repo**: call `digest` first — change-oriented briefing (~200 tokens) covering what changed since last session, hotspots, and dead code.
- **First call in any analysis session**: `get_repo_health` — one-call triage snapshot (symbol counts, dead code %, avg complexity, top hotspots, cycle count).
- Cold-start signature overview: `get_repo_map` (token-budgeted, PageRank-ranked signatures — "what matters here?"); `get_symbol_importance` (top symbols by import-graph centrality, `pagerank` or `degree`).
- Start with `search_symbols`, `get_file_outline`, `get_repo_outline` for orientation. Never `Read` a source file to "see what's in it."
- `get_file_tree` for a scoped directory listing within the index; `get_file_content` to fetch a cached file or line range (prefer over `Read` on indexed repos).
- `get_session_context` — check files already accessed this session before re-reading. `get_session_snapshot` — ~200-token markdown summary for post-compaction continuity.

**Retrieval**:
- Before editing a function, call `get_symbol_source` for that function, not `Read` on the whole file. For multi-symbol context, use `get_context_bundle`.
- For query-driven context assembly in one call, use `assemble_task_context` — it auto-classifies intent, runs the right sub-tools, and returns a source-attributed capsule.
- For token-budgeted relevance-ranked context without specifying symbols: `get_ranked_context` (BM25 + PageRank, configurable strategy and scope).
- `search_text` for full-text/regex search across file contents when symbol search misses (string literals, comments, config values) — supports `context_lines` like `grep -C N`.
- `search_columns` for column metadata in dbt/SQLMesh repos — 77% fewer tokens than grep.
- Use `winnow_symbols` when you have multiple constraints (kind + complexity + decorator + churn + importance). One call instead of five.
- Results carry `_meta.confidence` — prefer high-confidence hits; re-query or fall back to serena when confidence is low.
- Run `check_embedding_drift` (or via `/health`) to catch index staleness before it silently degrades retrieval quality.

**References & call graph**:
- `find_references` — where is an identifier imported or re-exported. `find_importers` — which files import a given file. `check_references` — quick `is_referenced` bool for dead-code detection (import + content in one call).
- `get_dependency_graph` — file-level import graph up to 3 hops (imports / importers / both). `get_dependency_cycles` — detect circular import chains before a refactor.
- `get_call_hierarchy` — incoming callers and outgoing callees N levels deep. `get_impact_preview` — full transitive call-graph walk showing what breaks before deleting or renaming a symbol.
- `find_implementations` — concrete implementations of an interface/abstract class (multi-source, confidence-scored). `get_class_hierarchy` — full ancestor/descendant tree across Python, Java, TS, C#.
- `get_related_symbols` — heuristic cluster of nearby symbols (same-file + shared importers + name tokens); useful for orientation on unfamiliar code.
- For type resolution, interface/trait dispatch, or "find all callers across files," prefer **serena** — its LSP backing outperforms AST-only search on Python/TS/Rust/Go/C#.

**Refactoring & safety**:
- Before committing to a change, call `get_blast_radius` (transitive call-graph blast radius — what else breaks) AND `check_edit_safe` (regression risk + signature impact + complexity + test coverage + runtime traffic) — these are complementary, not alternatives. For PRs, `get_pr_risk_profile` produces a single composite score.
- Before renaming a symbol: `check_rename_safe`. Before deleting: `check_delete_safe`. Before editing (regression risk + signature impact + complexity + test coverage + runtime traffic): `check_edit_safe`. For multi-file rename/move/extract: `plan_refactoring` generates edit-ready blocks.
- Before refactoring unfamiliar code: `get_symbol_provenance` — full authorship lineage explains the "why" behind code before you change it.
- After editing files: call `register_edit` to invalidate BM25/search caches.
- `get_symbol_diff` — diff symbol sets between two indexed snapshots (index branch A as repo-main, branch B as repo-feature, then diff).
- `get_coupling_metrics` — afferent/efferent coupling + instability score for a module. `get_extraction_candidates` — functions worth extracting (high complexity + multi-file callers).

**Quality & risk**:
- `get_hotspots` — top-N highest-risk symbols (complexity × churn, CodeScene methodology); use before planning sprint work or targeting reviews.
- `get_churn_rate` — git churn for a file or symbol (commit count, authors, churn/week, stable/active/volatile).
- `get_symbol_complexity` — cyclomatic complexity, nesting depth, param count for a single symbol.
- `find_dead_code` — files/symbols with zero importers and no entry-point role (confidence-scored; prefer `get_dead_code_v2` for multi-signal).
- `get_file_risk` — per-symbol composite risk (0–100) for one file: complexity, exposure, churn, test-gap axes.
- Architecture deep-dives: `get_tectonic_map` (module topology + misplaced files), `get_signal_chains` (HTTP/CLI/event → call graph), `render_diagram` (any graph tool output → Mermaid), `get_project_intel` (Dockerfiles, CI, manifests cross-linked to code), `get_layer_violations` (layer boundary checks).
- Quality scans: `search_ast` for anti-pattern/security sweeps; `find_similar_symbols` for consolidation candidates; `get_dead_code_v2` for multi-signal dead code; `diff_health_radar` to compare health before/after a PR.
- For security/quality gate before merge: `search_ast(category="security")` + `get_dead_code_v2` + `get_untested_symbols` together form the pre-merge checklist.
- Periodically run `audit_agent_config` to catch stale symbol refs and dead paths in CLAUDE.md itself — keeps routing rules lean.

**Cross-repo & monorepos**:
- `get_cross_repo_map` — which indexed repos depend on which at the package level. `get_group_contracts` — de-facto API surface across a group (de_facto_api / leaky_internal / dead_contract / version_skew tiers).
- `list_workspaces` — enumerate monorepo workspace members (pnpm, yarn, turborepo, Go, Cargo); use returned `path` as `scope_path` in `get_project_intel`.

**Session & tier config**:
- `set_tool_tier` — explicit tier override (core/standard/full) when you hit a capability-gated failure mid-task. `announce_model` — self-report active model for automatic tier selection (idempotent; call plan_turn instead for routine per-task use).
- `get_session_stats` — token savings stats for the current session; quantify retrieval-stack cost reduction before/after routing changes.
- `analyze_perf` — per-tool latency telemetry; identify slow tools and cold caches.
- `tune_weights` — learn per-repo BM25 retrieval weights from the ranking ledger; run after search-quality changes to recalibrate relevance.
- `test_summarizer` — verify AI summarizer connectivity and output; debug missing or stale symbol summaries.

### 2. Data work — jDataMunch for CSVs, DuckDB for real SQL
- For any CSV / TSV: `describe_dataset` first, `get_rows` with filters next,
  `aggregate` for group-bys. Do **not** dump the file into context.
- For Parquet, JSON, remote data (S3 / GCS / R2), or anything involving
  joins across multiple sources, call **duckdb** directly — it runs real
  SQL in-process.
- For correlations: `get_correlations`. For cross-dataset work:
  `join_datasets`.
- For ad-hoc SQL within a single indexed dataset: `plan_query` then
  `run_sql` — lighter than DuckDB for single-file queries.
- Before deep analysis: `get_dataset_health` to catch schema issues early.

### 3. Docs work — jDocMunch (mine), Context7 (theirs)
- For project docs, runbooks, and internal markdown: **jdocmunch**. Ask for
  sections by heading, not whole files.
- **Retrieval flow:** `search_sections` for content search; `search_titles` for fast
  heading-text navigation (no embeddings); `get_section_excerpt(s)` to peek before
  full reads; `get_section_summary(ies)` for metadata without content reads.
- **Section navigation:** `describe_section` (v1.54+ — metadata + breadcrumb + neighbors
  in one call, saves three round-trips); `get_section_path` for breadcrumb chain;
  `section_neighbors` for prev/next/parent/first_child; `get_section_descendants` for
  full subtree BFS; `get_related_sections` for structural + semantic neighbors;
  `get_tutorial_path` for ordered tutorial chains; `get_section_diff` for
  snapshot-vs-disk comparison.
- **Doc quality checks:** `get_doc_health` (one-shot index diagnostics — run first);
  `get_index_overview` (repo snapshot: counts, formats, top tags/roles); `get_orphan_sections`
  (zero inbound links); `get_recent_changes` (disk-drifted sections — pre-flight before
  re-index); `get_doc_coverage`, `get_backlinks`, `get_broken_links`, `get_stale_pages`,
  `get_wiki_stats` — run before major doc updates or when doc quality is in question.
- **Code ↔ doc bridges:** `get_undocumented_symbols` (code symbols absent from docs);
  `link_code_to_symbols` (doc code blocks → jcodemunch symbols); `find_code_examples`
  (search fenced code blocks by BM25).
- **OpenAPI / schema:** `find_endpoint` (by path glob/method/tag); `list_endpoints_by_tag`;
  `find_operations_using_schema`; `get_schema_graph` (BFS walk of schema refs).
- **Tagging & glossary:** call `get_all_tags` / `get_all_roles` to discover namespaces
  before building tag-filtered `search_sections` queries; `list_terms` / `lookup_term`
  for glossary entries.
- **Index management:** `define_repo_group` / `list_repo_groups` for fan-out search
  across multiple repos; `check_embedding_drift` + `verify_index` for integrity;
  `tune_weights` for ranking; `analyze_perf` / `get_session_stats` for perf;
  `list_docs` for flat per-doc inventory.
- For third-party library docs (FastAPI, React, Django, etc.), **context7**
  is authoritative and version-pinned. Call it whenever the question
  references a named library.

### 4. Memory — mempalace before WebSearch or re-asking
- Start every non-trivial task with a `mempalace` search for prior work on
  the same topic. "Have we solved this before?" is always question #1.
- On session close (or before compaction), snapshot the session into
  MemPalace so the next session starts with context.
- Organize mines by wing (person/project) so scopes stay tight.
- Use `mempalace_diary_write` for per-session notes — entries are now
  scoped per-project automatically (mempalace 3.3.3+).

### 5. Runtime traces (when available)
- After ingesting OTel/SQL/stack traces via `import_runtime_signal`, use:
  - `find_hot_paths` — top-N symbols by runtime hit count; pairs with `get_blast_radius`
    to answer "is this PR touching code that runs 4M times/day?"
  - `find_unused_paths` — reachable code never executed (runtime blind spots)
  - `get_runtime_coverage` — coverage histogram: symbols with vs without runtime evidence
  - `get_redaction_log` — verify PII redaction chokepoint is firing
- Skip these when no traces have been ingested — tools return empty results and say so.

### 6. Verification step
- Before finalizing code changes, run a verification pass using
  `get_changed_symbols` (git diff → symbols touched),
  `get_untested_symbols`, and `get_pr_risk_profile`. Report the risk score
  to the user.

### 7. Format economy
- Pass `format="auto"` on any jCodeMunch tool call that might return a large
  response. This triggers the MUNCH compact wire format when savings are
  ≥15%.

## When to fall back to Read / Grep / Bash

Only when:
- The request is about a file type none of the above tools understand
  (e.g., binary, image, exotic format).
- An indexing step has failed and I've told the user about it.
- The user explicitly asks for native file access.

In those cases, say so out loud before switching tools.

## When to stop and ask

If two routes both look valid and the choice materially affects cost, speed,
or accuracy, ask the user which they want rather than guessing. For
everything else, pick the first-choice tool and proceed.

---

*Stack installed from `C:\Users\wblair\Downloads\claude\_stack_setup\` —
see `README.md` there for install / verify / re-register instructions.*

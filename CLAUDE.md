# Retrieval Stack Routing Policy

You have a dedicated retrieval stack installed. **Always consult it before
falling back to brute-force file reading, grep, or bash.** Brute-force
reading is a last resort, not a default.

The stack lives at `$STACK_ROOT` — `/opt/proj/Uncle-J-s-Refinery` on Linux,
`/c/opt/proj/Uncle-J-s-Refinery` in Git Bash on Windows. **Never paste a literal
`/opt/proj/...` path into a shell without checking the host first.** On Windows
that path does not exist, and the command fails with a bare "No such file or
directory" that reads like a missing tool rather than a wrong prefix.

The jcodemunch, jdatamunch, and jdocmunch MCP servers run as entry points under
`$STACK_ROOT/.venv/bin/`; serena, context7, and duckdb are launched via
`uvx`/`npx`. Registered commands are in
`$STACK_ROOT/mcp-clients/claude-code-mcp.json`.

**This policy is global — it applies in every project, not just the stack repo.**
The servers are registered at user scope, so they are reachable from any working
directory. But reachable is not indexed: **a new project has no index until you
make one.** Call `list_repos` first; on a miss run `index_folder` (jcodemunch)
and `index_local` (jdocmunch) before concluding anything is absent. An unindexed
repo returns empty results that are indistinguishable from a genuine absence —
see the absence contract below, and treat a bare empty result as `degraded`.

`context7` exists only where Node.js is installed. If it is not registered, use
WebSearch/WebFetch for third-party library docs and say that you fell back.

## Tools by modality — first choice wins

| Request shape                                   | Primary tool                      | Fallback                          |
| ----------------------------------------------- | --------------------------------- | --------------------------------- |
| Source code: find / read / analyze a symbol     | **jcodemunch**                    | serena, then Read/Grep            |
| Source code: cross-file refs, types, generics   | **serena** (real LSP)             | jcodemunch                        |
| CSV / TSV / small tabular file                  | **jdatamunch**                    | duckdb                            |
| Parquet / S3 / complex SQL / joins across files | **duckdb** (MotherDuck MCP)       | jdatamunch                        |
| My own project docs / runbooks / markdown       | **jdocmunch**                     | Read                              |
| Third-party library documentation               | **context7**                      | WebSearch/WebFetch                |
| "What did we decide / discuss / build before?"  | **memweave** (`mw_search.py`)     | session transcript                |
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
- `index_dependency` — index an INSTALLED third-party dependency (the exact version in node_modules or the repo's .venv) as its own queryable repo; ground-truth a library's API instead of guessing. Prefer over context7 when you need the installed version's actual source, not published docs.

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
- **A zero-result scan is not proof of absence.** The server distinguishes `absent` (the scan
  covered the tree and found nothing) from `degraded` (stale, partial, truncated, or mid-rebuild —
  it could not have found it). Only `absent` licenses "this symbol does not exist"; on `degraded`,
  re-index and re-query before reporting absence. This install runs the default `meta_fields: []`,
  which strips `_meta.verdict` before you see it — what survives is `_meta.absence_evidence`
  carrying `citable` and `blocked_by`. Treat a bare empty result as `degraded` until something
  says otherwise.
- Run `check_embedding_drift` (or via `/health`) to catch index staleness before it silently degrades retrieval quality.

**References & call graph**:
- `find_references` — where is an identifier imported or re-exported. `find_importers` — which files import a given file. `check_references` — quick `is_referenced` bool for dead-code detection (import + content in one call).
- `get_dependency_graph` — file-level import graph up to 3 hops (imports / importers / both). `get_dependency_cycles` — detect circular import chains before a refactor.
- `get_call_hierarchy` — incoming callers and outgoing callees N levels deep. `get_impact_preview` — full transitive call-graph walk showing what breaks before deleting or renaming a symbol.
- `get_endpoint_impact` — "what breaks if I change this HTTP endpoint?" — handler + importers + callers + rendered templates; resolves string-dispatch (Django/Express/Flask/Rails) and decorator (Flask/FastAPI/Spring) routes. Endpoint-scoped counterpart to `get_blast_radius`; pass `include_infra` to attach env/compose/K8s exposure.
- `find_implementations` — concrete implementations of an interface/abstract class (multi-source, confidence-scored). `get_class_hierarchy` — full ancestor/descendant tree across Python, Java, TS, C#.
- `get_related_symbols` — heuristic cluster of nearby symbols (same-file + shared importers + name tokens); useful for orientation on unfamiliar code.
- For type resolution, interface/trait dispatch, or "find all callers across files," prefer **serena** — its LSP backing outperforms AST-only search on Python/TS/Rust/Go/C#.

**Refactoring & safety**:
- Before committing to a change, call `get_blast_radius` (transitive call-graph blast radius — what else breaks) AND `check_edit_safe` (regression risk + signature impact + complexity + test coverage + runtime traffic) — these are complementary, not alternatives. For PRs, `get_pr_risk_profile` produces a single composite score.
- Before renaming a symbol: `check_rename_safe`. Before deleting: `check_delete_safe`. Before editing (regression risk + signature impact + complexity + test coverage + runtime traffic): `check_edit_safe`. For multi-file rename/move/extract: `plan_refactoring` generates edit-ready blocks.
- Before refactoring unfamiliar code: `get_symbol_provenance` — full authorship lineage explains the "why" behind code before you change it.
- After editing files: call `register_edit` to invalidate BM25/search caches.
- `get_symbol_diff` — diff symbol sets between two indexed snapshots (index branch A as repo-main, branch B as repo-feature, then diff).
- `get_parity_map` — migration/port parity between a source and target tree (two subpaths or two repos): `ported`, `ported_diverged` (the counterpart drifted — the case a name-only check calls done), `unported`, `orphaned`, `added`. Rename-aware; `include_port_plan` orders unported symbols leaves-first with `blocking_deps`. Read-only and plan-only.
- `get_coupling_metrics` — afferent/efferent coupling + instability score for a module. `get_extraction_candidates` — functions worth extracting (high complexity + multi-file callers).

**Quality & risk**:
- `get_hotspots` — top-N highest-risk symbols (complexity × churn, CodeScene methodology); use before planning sprint work or targeting reviews.
- `get_churn_rate` — git churn for a file or symbol (commit count, authors, churn/week, stable/active/volatile).
- `get_delivery_metrics` — durable-change delivery over a window: commits_durable (landed and stuck) vs churn-back; the honest numerator for cost-per-outcome, not raw activity. Local-indexed repos only; trailing signal (recent commits flagged provisional).
- `get_symbol_complexity` — cyclomatic complexity, nesting depth, param count for a single symbol.
- `find_dead_code` — files/symbols with zero importers and no entry-point role (confidence-scored; prefer `get_dead_code_v2` for multi-signal).
- `get_file_risk` — per-symbol composite risk (0–100) for one file: complexity, exposure, churn, test-gap axes.
- Architecture deep-dives: `get_tectonic_map` (module topology + misplaced files), `get_signal_chains` (HTTP/CLI/event → call graph), `render_diagram` (any graph tool output → Mermaid), `get_project_intel` (Dockerfiles, CI, manifests cross-linked to code), `get_layer_violations` (layer boundary checks), `get_architecture_metrics` (Gini concentration over symbols/size/fan-in/fan-out, Lakos depth, DSM modularity — answers "is coupling piling up in a few files?", which a ranked list of peaks cannot), `get_decorator_census` (normalized repo-wide `@route`/`@fixture`/`[Serializable]` histogram + sites; pairs with `get_signal_chains`/`get_endpoint_impact`).
- Quality scans: `search_ast` for anti-pattern/security sweeps; `find_similar_symbols` for consolidation candidates; `get_dead_code_v2` for multi-signal dead code; `diff_health_radar` to compare health before/after a PR.
- For security/quality gate before merge: `search_ast(category="security")` + `get_dead_code_v2` + `get_untested_symbols` together form the pre-merge checklist.
- Periodically run `audit_agent_config` to catch stale symbol refs and dead paths in CLAUDE.md itself — keeps routing rules lean.

**Cross-repo & monorepos**:
- `get_cross_repo_map` — which indexed repos depend on which at the package level. `get_group_contracts` — de-facto API surface across a group (de_facto_api / leaky_internal / dead_contract / version_skew tiers).
- `list_workspaces` — enumerate monorepo workspace members (pnpm, yarn, turborepo, Go, Cargo); use returned `path` as `scope_path` in `get_project_intel`.

**Session & tier config**:
- `set_tool_tier` — explicit tier override (core/standard/full) when you hit a capability-gated failure mid-task. `announce_model` — self-report active model for automatic tier selection (idempotent; call plan_turn instead for routine per-task use).
- `suggest_corrections` — mine retrieval-regret telemetry (re-query churn, low confidence, vocab gaps) for prioritized CLAUDE.md routing/glossary fixes as unified-diff previews + index-freshness hints + a dry-run weight proposal; read-only, never writes your files. Complements `audit_agent_config`/`tune_weights`. Requires perf telemetry.
- `get_session_stats` — token savings stats for the current session; quantify retrieval-stack cost reduction before/after routing changes.
- `analyze_perf` — per-tool latency telemetry; identify slow tools and cold caches.
- `tune_weights` — learn per-repo BM25 retrieval weights from the ranking ledger; run after search-quality changes to recalibrate relevance.
- `test_summarizer` — verify AI summarizer connectivity and output; debug missing or stale symbol summaries.
- `finalize_handoff` — close a completed audit with one canonical Markdown handoff
  (`jcodemunch.handoff/v1`). The server validates every `evidence_refs` entry against what this
  session actually retrieved and fails closed on unknown refs, so the handoff attests rather than
  asserts; returns `{handoff_id, resource_uri, sha256}` and the immutable body reads from
  `munch://handoff/<id>`. To claim absence, cite the `absent:` ref from the scan that found
  nothing — a truncated or non-`absent` scan is refused. Never writes to the repo. Same contract
  in jdatamunch and jdocmunch.

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
- **Quality & risk:** `data_health_radar` (six-axis: null, type, cardinality, pk, semantic, stability + A-F grade) + `diff_data_health_radar` for snapshot deltas; mirrors jcm/jdoc health-radar pattern.
- **Schema safety:** `check_column_drop_safe` before any column drop (fuses PK/FK/runtime signals); `get_schema_impact` for transitive blast-radius of a schema change; `get_schema_drift` to compare two indexed dataset versions.
- **Discovery:** `find_similar_columns` for cross-dataset column dedup; `suggest_joins` for FK candidates; `find_unused_columns` (requires `ingest_sql_log` runtime data); `get_session_stats` for token savings.
- **Absence:** `search_data` carries the same verdict contract as jcodemunch — a non-`ok` state means the scan could not answer, not that the data is missing. Re-query or widen scope before concluding absence.
- **Handoff:** close a multi-step data audit with `finalize_handoff` — `evidence_refs` accept only column ids (`<dataset>::<column>#column`) or dataset names this session actually retrieved.

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
  snapshot-vs-disk comparison; `get_section_blast_radius` for transitive change impact;
  `check_section_delete_safe` before deleting a section.
- **Doc quality checks:** `get_doc_health` (one-shot index diagnostics — run first); `doc_health_radar`
  (six-axis: freshness, links, orphans, embeddings, roles, drift + A-F grade) +
  `diff_doc_health_radar` for snapshot deltas; `get_doc_pr_risk_profile` for composite
  PR risk across changed sections; `get_index_overview` (repo snapshot: counts, formats,
  top tags/roles); `get_orphan_sections` (zero inbound links); `get_recent_changes`
  (disk-drifted sections — pre-flight before re-index); `get_doc_coverage`, `get_backlinks`,
  `get_broken_links`, `get_stale_pages`, `get_wiki_stats` — run before major doc updates
  or when doc quality is in question; `find_similar_sections` for near-duplicate/
  overlapping section detection; `count_sections` for fast headcount without ranking.
- **Code ↔ doc bridges:** `resolve_related_code_repos` — maps a jdocmunch docs repo to candidate jcodemunch code repo handles by source_root; call first to get the right `code_repo` arg for the bridge tools below; `get_undocumented_symbols` (code symbols absent from docs);
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
  `list_docs` for flat per-doc inventory; `get_doc` (v1.58+) for single-doc detail
  view (section list, role/tag distributions, byte_size, format, indexed_at) —
  pairs with `list_docs`.
- **`index_local` needs explicit paths as of v1.130.0.** An argless refresh no longer
  widens the corpus, and v1.126.1 skips **all** dot-directories by rule rather than by a
  list of twelve — so content previously indexed under e.g. `.claude/` disappears on
  re-index, and newly added directories are not picked up unless you pass `paths=` (or
  `include_dot_dirs=` by directory NAME, not path). A refresh that silently shrinks the
  corpus looks identical to a successful one; check `corpus_selection_changed` and the
  `deleted` count in the result before trusting it.
- **v1.126.0 rescaled retrieval confidence.** Any threshold calibrated on the old scale is
  wrong. The exact old→new scale is **unverified** — treat returned confidence as ordinal
  (compare hits against each other), not against a remembered absolute cutoff.
- For third-party library docs (FastAPI, React, Django, etc.), **context7**
  is authoritative and version-pinned. Call it whenever the question
  references a named library.

### 4. Memory — memweave before WebSearch or re-asking
- Start every non-trivial task with a memory search for prior work on the same topic.
  "Have we solved this before?" is always question #1. Run:
  `"$STACK_ROOT/.venv-memweave/bin/python" \`
  `  "$STACK_ROOT/scripts/memweave/mw_search.py" "your query" --k 5`
  Substitute the real `$STACK_ROOT` for the host (see top of file) — the shell
  does not have it exported. From inside the stack repo, the relative form
  `.venv-memweave/bin/python scripts/memweave/mw_search.py "..." --k 5` works
  as-is and is the safer default.
  (offline ONNX semantic + BM25 over `~/.uncle-j-memory`; add `--json` for machine-parseable
  output, `--min-score N` to threshold). It opens the existing index read-only — no writes.
- **memweave ships no MCP server** — it's a separate-process Bash CLI, not an MCP tool. Use Bash
  to invoke `mw_search.py`; do not look for a `memweave_*` MCP tool.
- A missing/empty store exits nonzero with a clear message — fall back to the session transcript.
- **Freshness is automatic, but not equally everywhere.** The `uncle-j-memweave-sync` cron runs
  `sync_memory.sh --all` nightly at 02:30 and covers **every** project. The session-end Stop-hook
  is registered in the stack repo's own `.claude/settings.json`, so it fires **only when the
  session's cwd is the stack repo** — 297 of 297 hook runs to date were
  `project=-opt-proj-Uncle-J-s-Refinery`. Work done in any other project reaches the store at the
  02:30 cron, not at session close. Either way there is no manual snapshot step.
- The store is **rebuildable from the markdown corpus** at `~/.uncle-j-memory` (rm the sqlite index
  → byte-identical rebuild via `sync_memory.sh`); the markdown is the source of truth, not the index.
- Scope: `~/.uncle-j-memory` is the **cross-project** store — the nightly `--all` export covers
  every project under `~/.claude/projects` (34 as of 2026-08-19), not just this one. Search it for
  prior art regardless of which project you are working in.
- **Two corpus sources, not one.** Transcripts (`memory/*.md`, what was *said*) and a mirror of the
  Obsidian vault (`memory/vault/**`, what was *decided* — VAULT-INDEX, Active Priorities, the
  per-project notes, and the Jobs). Before the mirror, "have we solved this before?" searched past
  the one store holding the decisions. Both are derived: **never edit `memory/vault/` — edit the
  vault at `/opt/proj/jaredrhod/vaults/brain`**, or the next sync overwrites you.
- **The vault mirror lags up to ~24h.** It rides `sync_memory.sh`, and vault edits happen in
  `/opt/proj/jaredrhod`, whose only Stop hook is `vault-session-check.sh` — not the memweave sync.
  So a note written today reaches the store at the 02:30 cron, not at session close. A same-day
  miss is staleness, not absence; check the vault directly when the question is about work done
  today.
- **The mirror excludes `11 - Personal` and `12 - Archive` and fails closed.** Personal Context
  holds health, key people, and beliefs the vault's own rules keep out of every boot-loaded file;
  the Archive carries a plaintext credential. Any top-level vault folder that
  `scripts/memweave/mirror_vault.py` does not recognise is **also** excluded and reported with a
  non-zero exit — classify a new folder there before expecting to search it.

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
- On `get_ranked_context`, pass `compress=True` to fit more symbols into the same token budget —
  keystone-protected structural compression prunes low-signal lines from oversized bodies while
  always keeping signatures, control flow, and returns. Pruned items carry `source_pruned`.
- `get_symbol_source` no longer returns `content_hash` by default (since v1.108.208). Pass
  `verify=True` when you need the digest — e.g. to detect source drift, or to cite the symbol in
  a `finalize_handoff` evidence ref.

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

## Output Token Economy
<!-- user-added: preserve this section manually during upgrades — no automated enforcement -->
<!-- source: jgravelle/jOutputMunch@d46c99c — rules/core.md + rules/code-assistant.md + rules/mcp.md -->
<!-- partial adaptation: filler-opener and closer-phrase rules omitted (covered by existing project guidelines) -->

Rules adapted from jOutputMunch. TODO: propagate relevant rules to prose-generating skills (see Task #3).

### Response behavior
- Don't narrate the search process. "First I looked at X, then Y" → just say "It's in Z:42."
- Don't re-quote tool results in the response. Reference line numbers or function names.
- Don't summarize what a tool returned before answering — respond to the actual question.
- Don't repeat the user's request before acting on it. Act.
- One qualifier per claim maximum. Pick the most accurate one; drop the rest.
- Use contractions. "It is" → "It's".
- Prefer short sentences. Each clause after a comma costs tokens. A sentence with three commas should usually be two sentences.
- Don't restate what was just established. If the previous sentence said X, the next sentence should not rephrase X before adding Y. Just add Y.

### Vocabulary — avoid these (add tokens, subtract clarity)
`delve` `tapestry` `leverage` `multifaceted` `groundbreaking` `seamless` `utilize`
`harness` (vague-verb sense only — technical noun permitted) `foster` `bolster` `elevate`
`reimagine` `revolutionize` `spearhead` `navigate` `illuminate` `transcend` `resonate`
`showcase` `entwine` `amplify` `augment` `maximize` `champion` `uncover` `unveil`

### MCP tool responses (for MCP server authors)
Tool descriptions teach (read once). Tool results report (read per-call).
Keep usage hints in the description, not result payloads.
Return structured data (`{"error":"not_found"}`), not apologetic prose.
Omit `success: true` — absence of error implies success. Use `success: false` for non-exception failures.
Strip nulls and empty collections before serializing — use an explicit predicate, not truthiness:
`result = {k: v for k, v in result.items() if v is not None and v != [] and v != {}}`
Then serialize: `json.dumps(result, separators=(',',':'))` (no indent; whitespace only).

---

*Stack source and installer live at `$STACK_ROOT` (see top of file for the
per-host path) — see `README.md` there for install / verify / re-register
instructions. This file is deployed to `~/.claude/CLAUDE.md` by `install.sh` and
re-synced by `scripts/refinery-doctor.sh --fix`, both of which compare against
the repo copy and overwrite the deployed one. **Edit the repo copy. Edits made
only to `~/.claude/CLAUDE.md` are reverted on the next install or doctor run.***

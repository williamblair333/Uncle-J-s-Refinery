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
- `resolve_repo` converts any filesystem path to a repo ID in one O(1) lookup — faster than scanning `list_repos`. **It stops at a nested independent clone** (#492, verified against 1.108.288 at `tools/resolve_repo.py:53,343`): a separate repo checked out inside an indexed parent is *contained* by it on the filesystem but belongs to neither its corpus nor its history, so the parent is no longer returned as `indexed: true` for it. Pass `repo` explicitly if you actually wanted the outer one. Submodules deliberately still resolve to the parent — their content IS indexed there.
- **`CODE_INDEX_PATH` relocates the whole index root** (default `~/.code-index`; verified against 1.108.288 at `config.py:109,115`, `cli/receipt.py:161`). Store, lock, and config all honour it. An index built under a different value is simply not found — read that emptiness as `degraded`, never `absent`.
- `summarize_repo` regenerates AI summaries when skipped or interrupted; `embed_repo` warms the semantic-search cache upfront; `invalidate_cache` forces a full re-index.
- **`PARSER_GENERATION` went 1 → 7 in the 1.108.303 upgrade** (verified against installed
  1.108.303 at `storage/index_store.py:152,173,194,222`). Every indexed repo re-parses in full on
  its next index run, and three of the bumps change values already **stored per symbol** —
  incremental never re-reads unchanged content, so an un-re-indexed repo serves the old ones forever:
  - **gen 6 — `max_nesting` could not see Python control flow.** It counted BRACKETS, so
    `if`/`for`/`while` contributed nothing and the field reported the deepest *expression* under
    the same name. Measured 3 against an AST truth of 6 — an underreport by half, on the one axis
    separating a wide flat dispatcher from tangled logic. Now `max(bracket, indentation)`, which can
    only raise a depth; brace languages are unchanged. Read by `get_symbol_complexity`,
    `get_hotspots`, `get_extraction_candidates`, `get_pr_risk_profile`. Feeds no score, so no grade moves.
  - **gen 7 — Rust impl methods had no owner.** `impl Foo { fn new }` and `impl Bar { fn new }`
    both emitted a bare `new`, kind `function`, parent `None`, separated only by a `~1`/`~2` id
    suffix. On ripgrep, 1,331 of 3,514 symbols (37.9%) shared a bare name with a same-file sibling;
    after, 55 (1.6%). `qualified_name`, `kind` (2,199 Rust symbols promoted `function` → `method`)
    and `parent` all changed, and `search_symbols` / `find_references` / `check_rename_safe` read them.
  - **gen 5 — three Rust definition classes yielded no symbol at all**: `union`, a trait method
    with no default body (`function_signature_item`), and a `const`/`static` inside a function body.
- **Discovery skips widened; a file/symbol-count drop after re-index is the fix, not a loss**
  (verified at `security.py:306,326-333`). Newly skipped: `_build` (Elixir/Mix, Sphinx, Dune —
  `mix` copies dependency *sources* there, so those symbols were indexed twice) and the dotted
  JS/TS framework build trees `.next`, `.nuxt`, `.output`, `.svelte-kit`, `.angular`, `.turbo`,
  `.parcel-cache`, `.dart_tool` (transpiled copies competing against the real source in ranking).
  Dotted spellings only — `out`/`bin`/`obj`/`coverage` name real source dirs and stay indexed.
  Opt back in per-project with `exclude_skip_directories`; every skip is counted in `discovery_skip_counts`.
  Separately, **`.mts` and `.cts` now index as TypeScript** (`parser/languages.py:63`) — they
  parsed as nothing before, so their absence from any earlier result was coverage, not truth.
- **Racket is a supported language**, with two new config keys: `racket_definition_forms` (declare
  a project's own defining macros) and `racket_langs` (promote a `#lang` the parser does not know).
  Changing either re-parses that repo once, tracked by `CodeIndex.racket_config_digest` rather than
  a global generation bump; an index built before the stamp existed and holding Racket files also
  re-parses once (`tools/_utils.racket_reparse_reason`). **v1.108.310 replaced the tree-sitter path
  with a real `#lang`-aware Racket reader** (verified against installed 1.108.312 at
  `storage/index_store.py:361`, `tools/_utils.py:375`): a second stamp,
  `racket_reader_generation`, forces one more full re-parse of every local index holding `.rkt`,
  reason `racket_reader_changed`. `racket_langs` now also declares a lang's at-exp command
  character. Symbols and require edges read from a Racket repo indexed before that reader are not
  comparable to ones taken after.
- `suggest_queries` surfaces top entry-point files and ready-to-run example queries on an unfamiliar repo.
- `get_watch_status` — daemon coverage. **Do NOT read its `any_stale: false` as "the index is
  fresh."** Verified against 1.108.288 at `tools/get_watch_status.py:73,90`: staleness comes from
  `get_reindex_status`, which reads **in-process, in-memory** state. When the querying process
  never tracked a reindex — the normal case, because the watcher runs in the systemd daemon, a
  *different* PID — `has_any_reindex_state()` is False and every repo gets the hardcoded default
  `{"index_stale": False}`. `any_stale` then reports False having measured nothing. Observed here
  2026-08-21: all 18 repos `index_stale=false` **and** `watched_by_another_process=true`, including
  a repo whose index was demonstrably behind its working tree. Treat `any_stale: false` as
  `unknown`; use `_meta.verdict.channels.index` or `check_embedding_drift` for real freshness.
  (Upstream has the correct tri-state already — `FreshnessProbe.repo_freshness` in
  `retrieval/freshness.py:245` returns `fresh`/`stale`/`unknown`/`not_tracked`, and its docstring
  names this exact Boolean-has-nowhere-to-put-"I-could-not-find-out" defect. `get_watch_status` is
  the caller that still uses the Boolean it was written to replace.)
- `jcodemunch_guide` — returns the version-current CLAUDE.md policy snippet; prefer it over a static copy in any harness that auto-loads routing rules. **Its output is filtered** by `disabled_tools` and the active tier/profile (#495/#506, verified against 1.108.288), so it is a subset of the full policy — a tool missing from the guide is not a removed tool.
- `index_dependency` — index an INSTALLED third-party dependency (the exact version in node_modules or the repo's .venv) as its own queryable repo; ground-truth a library's API instead of guessing. Prefer over context7 when you need the installed version's actual source, not published docs.

**Orientation & cold-start**:
- Use `plan_turn` as your opening move on an unfamiliar repo. It respects the turn budget and selects the right tool for you.
- **Session start on a familiar repo**: call `digest` first — change-oriented briefing (~200 tokens) covering what changed since last session, hotspots, and dead code.
- **First call in any analysis session**: `get_repo_health` — one-call triage snapshot (symbol counts, dead code %, avg complexity, top hotspots, cycle count).
  - **`radar.composite` and `radar.grade` are now `null` whenever any axis could not be measured**
    (#562, v1.108.306, verified against installed 1.108.312 at `tools/health_radar.py:241-253`,
    `tools/get_repo_health.py:289-294,339`). Two causes: `get_dead_code_v2` returning
    `dead_symbols: []` *with* a `signal_warning` — a refusal, previously read as `dead_code_pct:
    0.0` and a perfect axis — and a shallow clone making `churn_surface` unmeasurable. Dropping the
    axis was measured to move the grade FURTHER from truth (84.0 B → 88.8 B against 77.3 C on a full
    clone), so the grade is withheld instead. New keys: `unmeasurable_axes`, `grade_withheld`, and
    `partial_composite` (the figure minus that axis — never rename it into `composite`). Body-level
    `dead_code_measurable` / `dead_code_signal_warning` name the refusal, and
    `coupling_entry_points_excluded` discloses the files the coupling ratio left out.
    **Comparing or averaging `composite` without a `None` check now raises.**
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
- Results carry `_meta.confidence` — prefer high-confidence hits; re-query or fall back to serena
  when confidence is low. **The scale is 0–1 and always was; what v1.108.265 fixed was the
  `strength` sub-signal reading a RAW score against a hardcoded BM25 curve in every mode**
  (verified against 1.108.288, `retrieval/confidence.py:51,110`). BM25 tops out in the tens, a
  cosine at 1.0, an RRF fused score at ~0.0164 — so the same ranking quality scored ~7x lower in
  hybrid than in lexical, for nothing but units. Each scorer now declares its ceiling.
  **Two consequences, and they are opposite:**
  - **Lexical/BM25 confidences did NOT move.** `BM25_CEILING = 12.0` makes the new
    `1-exp(-3t/12)` algebraically identical to the historical `1-exp(-t/4)` — the source says
    "EXACTLY" at `confidence.py:110`. A threshold you calibrated on BM25 is still correct.
  - **Hybrid/semantic confidences were understated** and moved up. Anything calibrated there was
    wrong in the direction of distrust, and was disqualifying searches from evidence they earned.
  Prefer comparing hits against each other. The one meaningful absolute is **0.4** — below it the
  server itself declines to mint a citable absence claim (`STATE_LOW_CONFIDENCE`). Same mechanism
  and same numbers in jdocmunch — see § 3.
- **`identity_type` no longer says `exact` for a normalised match** (#458, verified against
  1.108.288). `search_symbols` grades `exact` only at identity ≥ 50.0; a query that matched after
  tokenization folded case, underscores or punctuation is `normalized` (≥ 40.0), then `prefix`,
  `segment`, `none`. Filtering results on `identity_type == "exact"` silently drops real hits —
  accept the normalised tier too. (Case folding alone still counts as exact, deliberately.)
- **A zero-result scan is not proof of absence.** The server distinguishes `absent` (the scan
  covered the tree and found nothing) from `degraded` (stale, partial, truncated, or mid-rebuild —
  it could not have found it). Only `absent` licenses "this symbol does not exist"; on `degraded`,
  re-index and re-query before reporting absence. **`_meta.verdict` does reach you** — it carries
  `state`, `scanned`, `channels` and a `note`, and is populated on `search_text`, `get_blast_radius`
  and friends. (This bullet previously claimed `meta_fields: []` stripped it, leaving only
  `_meta.absence_evidence`; corrected 2026-08-21 after every call in a working session returned a
  populated verdict.) Treat a bare empty result as `degraded` until the verdict says otherwise.
- Run `check_embedding_drift` (or via `/health`) to catch index staleness before it silently degrades retrieval quality.
- **A store written across an embedding-model change holds two vector widths, and the matrix
  silently drops one of them** (#500, verified against 1.108.288 at `tools/embed_repo.py:411` and
  `storage/embedding_store.py:109`). For four releases the comment claimed model-change detection
  and the code did not implement it: `EmbeddingMatrix` infers its dimension from the FIRST row and
  discards every row that disagrees, so symbols embedded after a switch stop being searchable —
  silently and cumulatively. The producer is fixed, but **stores already in that state stay that
  way until the next model change or a forced `embed_repo`**. Watch `skipped_dim_mismatch` in
  `search_symbols` output; a non-zero value means you are searching a partial corpus.
  *This host, as of 2026-08-21:* clean — `check_embedding_drift` reports one model
  (`local_onnx` / `all-MiniLM-L6-v2`, dim 384, pinned 2026-05-25), `max_drift=0.0`, no alarm, so
  no switch has ever happened here. **That safety expires the moment `JCODEMUNCH_EMBED_MODEL`
  changes** — re-embed every repo if it does.

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
- **A shallow clone answers every churn question with a small number and exit 0, and the tools now
  say so** (v1.108.305, verified against installed 1.108.312 at `tools/_git_history.py:100,201`,
  `tools/get_hotspots.py:177-193`). `history_coverage` asks whether the history reaches past the
  `--since` window — coverage, not shallowness, so a deep-enough shallow clone is not flagged and a
  three-week-old repo is young rather than truncated. `get_hotspots` gains body-level
  `churn_measurable` (False ⇒ `_meta.confidence_level: "low"`, and `get_repo_health` withholds the
  grade); `get_churn_rate` and `get_hotspots` stamp `_meta.git_history` **only when coverage is not
  complete** — silence there means the window was covered. Tri-state: `complete: null` is "could not
  establish", never "fine". *On this host `meta_fields` is `null` (`~/.code-index/config.jsonc:38`),
  so `_meta` reaches us; on a default install (`meta_fields: []`) `_meta.git_history` is stripped and
  `churn_measurable` is the only surviving disclosure.*
- `get_delivery_metrics` — durable-change delivery over a window: commits_durable (landed and stuck) vs churn-back; the honest numerator for cost-per-outcome, not raw activity. Local-indexed repos only; trailing signal (recent commits flagged provisional).
- `get_symbol_complexity` — cyclomatic complexity, nesting depth, param count for a single symbol.
- `find_dead_code` — files/symbols with zero importers and no entry-point role (confidence-scored; prefer `get_dead_code_v2` for multi-signal). **Render edges now count as reachability** (#461, always-on, verified against 1.108.288 at `tools/find_dead_code.py:256`): a template reached only by `render(request, "page.html")` is no longer reported as `zero_importers` at confidence 1.0. The result set is smaller and more correct — a shrink here is the fix, not a regression. Deliberately not an extension exemption: a template nothing renders is still dead and still reported.
- `get_file_risk` — per-symbol composite risk (0–100) for one file: complexity, exposure, churn, test-gap axes.
- Architecture deep-dives: `get_tectonic_map` (module topology + misplaced files), `get_signal_chains` (HTTP/CLI/event → call graph), `render_diagram` (any graph tool output → Mermaid), `get_project_intel` (Dockerfiles, CI, manifests cross-linked to code), `get_layer_violations` (layer boundary checks), `get_architecture_metrics` (Gini concentration over symbols/size/fan-in/fan-out, Lakos depth, DSM modularity — answers "is coupling piling up in a few files?", which a ranked list of peaks cannot), `get_decorator_census` (normalized repo-wide `@route`/`@fixture`/`[Serializable]` histogram + sites; pairs with `get_signal_chains`/`get_endpoint_impact`).
  - **`get_architecture_metrics`: `concentration.gini.bytes_per_file` can now be `null`, and its basis changed** (v1.108.291, verified against installed 1.108.291 at `tools/get_architecture_metrics.py:160,176` and `tools/_utils.py:396`). It used to sum `byte_length` per file, which double-counts nesting — a class's span already covers its methods, so the number tracked how class-heavy a file was as much as how big it was (33.4% overall on the source repo, up to 2.28x on one file). It now merges each file's symbol spans and counts a byte once. Two consequences: a `bytes_per_file` Gini recorded before the upgrade is **not comparable** to one taken after, and the field is `null` — never `0.0` — when no file has trustworthy byte offsets, because `0.0` reads as "perfectly even" rather than "could not measure". Arithmetic on it without a `None` check now raises. New sibling keys `bytes_files_measured` / `bytes_unmeasurable_files` disclose the smaller file set the byte axis covers; the other three Gini axes still span every file.
- Quality scans: `search_ast` for anti-pattern/security sweeps; `find_similar_symbols` for consolidation candidates; `get_dead_code_v2` for multi-signal dead code; `diff_health_radar` to compare health before/after a PR.
- For security/quality gate before merge: `search_ast(category="security")` + `get_dead_code_v2` + `get_untested_symbols` together form the pre-merge checklist.
  - **`get_untested_symbols.untested_count` counted the PAGE, not the repository, until v1.108.306**
    (#559, verified against installed 1.108.312 at `tools/get_untested_symbols.py:195-211`). It was
    `len(symbols)` taken AFTER the `max_results` slice, and `reached_pct` divided by it — so
    `get_repo_health`, which calls with `max_results=1` because it "only needs the count", scored a
    perfect test axis on every repo with untested code (measured: 4,893 untested of 6,352, 23.0%
    reached, published as 100). `untested_count` and `reached_pct` are now repo-wide; the page length
    moved to the new `returned_count`. **Any coverage figure quoted from this tool before the upgrade
    is wrong in the flattering direction — re-run it.**
  - **Framework-declared entry points now count as roots** (#561/#562, `tools/_entry_points.py`,
    read by `find_dead_code`, `get_dead_code_v2`, `get_coupling_metrics`, `get_repo_health`). The
    index already stored each profile's `entry_point_patterns` — Next.js `route.ts` / `page.tsx` /
    `layout.tsx` / `middleware.ts`, Gin's `cmd/` — and nothing read them, so every consumer fell back
    to a Python-only filename list. A smaller dead-code result on a JS/TS framework repo is the fix.
    ⚠ `matches() == False` is not "ordinary module": no detected profile means no declaration was
    available — read `profile_name: null` as unknown.
- Periodically run `audit_agent_config` to catch stale symbol refs and dead paths in CLAUDE.md itself — keeps routing rules lean.

**Cross-repo & monorepos**:
- `get_cross_repo_map` — which indexed repos depend on which at the package level. `get_group_contracts` — de-facto API surface across a group (de_facto_api / leaky_internal / dead_contract / version_skew tiers).
- `list_workspaces` — enumerate monorepo workspace members (pnpm, yarn, turborepo, Go, Cargo); use returned `path` as `scope_path` in `get_project_intel`.

**Session & tier config**:
- `set_tool_tier` — explicit tier override (core/standard/full) when you hit a capability-gated failure mid-task. `announce_model` — self-report active model for automatic tier selection (idempotent; call plan_turn instead for routine per-task use).
  - **A mid-session NARROWING that cannot repay its own cache invalidation is now refused**
    (v1.108.311, verified against installed 1.108.312 at `server.py:6842-6866,903-925`,
    `tier_switch_cost.py:82-104`). The tool block is serialised ahead of system and messages, so
    shrinking it invalidates the schema block *and every accumulated turn*, then cache-writes the new
    one at full rate. Measured on this catalog: `full` → `standard` drops 6.7% of the payload and
    needs **174 requests** to break even, before any history. So `set_tool_tier("core")` mid-task can
    come back `{"ok": true, "changed": false, "refused": "switch_does_not_pay"}` with `reason` and
    `switch_cost` in the BODY — **`ok: true` no longer means the tier moved; read `changed`.**
    `announce_model` refuses the same way and leaves the tier where it was. **Widening is never
    refused**, so escalating after a capability-gated failure still works — which is the only reason
    this file tells you to call it. To actually run narrow, set `tool_profile` at startup, where
    there is no switch to pay for.
  - **Schema-token counts carry `schema_tokens_basis`** (v1.108.312, `tier_switch_cost.py:43`,
    `server.py:585`): `one_time_at_full_rate_then_cache_read`. `schema_tokens_avoided` is payload
    size, NOT a per-request saving — this host measured 86% of baseline input cached, so reading it
    per-request overstates the impact by roughly an order of magnitude.
- `suggest_corrections` — mine retrieval-regret telemetry (re-query churn, low confidence, vocab gaps) for prioritized CLAUDE.md routing/glossary fixes as unified-diff previews + index-freshness hints + a dry-run weight proposal; read-only, never writes your files. Complements `audit_agent_config`/`tune_weights`. Requires perf telemetry. **Now also returns an `inflation` block** (v1.108.290, verified against installed 1.108.291 at `tools/suggest_corrections.py:363`, `retrieval/regret.py:352`): calls per information need, where a need is `(session_uid, query_hash)` — clusters name *which* queries went wrong, inflation says what the wrongness cost. **Its basis is CALLS, not tokens** — the ledger has no token column, and the field says so. It is always present but often `measurable: false`; read `reason` (`no_events` / `too_few_needs` / `ledger_has_no_session_column` / `no_repo`) rather than reading its absence as zero inflation. `repeats_after_index_change` is disclosed and deliberately *not* subtracted from the ratio. `digest` surfaces the same ratio in its regret line, but only when measurable and > 1.0.
- `get_session_stats` — token savings stats for the current session; quantify retrieval-stack cost reduction before/after routing changes. **Savings figures dropped to a corrected basis on 2026-08-22** (generation 2, verified against installed 1.108.291 at `storage/token_tracker.py:58,556`): the `raw_bytes` baseline stopped summing nested symbol spans and stopped charging a file once per symbol selected from it, both of which over-counted — so pre-2 counts read HIGH, and lifetime totals spanning the change are not one measurement. Nothing was rewritten; the mixed basis is disclosed instead, via `total_tokens_saved_basis.mixed_basis`. Check that flag before quoting a lifetime total. New alongside it: `lifetime_by_tool`, `lifetime_by_tool_since`, and `lifetime_unattributed` (what the meter earned before it could attribute anything — the shortfall is history, not missing data).
- `analyze_perf` — per-tool latency telemetry; identify slow tools and cold caches.
  **`cache.totals.hit_rate` is RAW key-presence, not validity** (v1.108.304-era fix, verified
  against installed 1.108.303 at `tools/analyze_perf.py:257-284`): the session LRU is invalidated
  only by index-mutating tools *in this process*, so an out-of-process reindex — the PostToolUse
  `index-file` spawn, the watcher, a second server instance — leaves stale entries serving and
  counting as hits. Published now only alongside `hit_rate_basis`, `hit_rate_revalidated`,
  `hits_validated_fresh` / `hits_validated_stale`, `hits_unvalidated` and `validated_share`.
  Quote the revalidated number; of the three result-cache consumers only `search_symbols`
  revalidates, so `hits_unvalidated` is genuinely UNKNOWN and is never folded into either bucket.
  **Two additions in v1.108.309** (verified against installed 1.108.312 at
  `tools/analyze_perf.py:53-107,356-358`): a second ranking, `heaviest_by_total_ms` — wall-clock
  actually consumed, which disagrees with `slowest_by_p95` whenever a fast tool is called often —
  and `compare_release` deltas that come back `null` with a `not_comparable` reason instead of
  differencing against an absent baseline field. The shipped baseline carries `tokens_saved` alone,
  so a tool at p95 900 ms used to publish `p95_delta_ms: 900.0`, read by anyone as a 900 ms
  regression against a release that never timed it. Calls and tokens still difference (their zero is
  real); latency does not.
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
- **Column profiles disclose their own staleness (v1.30.0+, verified against installed 1.31.7 at
  `tools/describe_column.py:167-190`).** A profile is served from the indexed snapshot, so
  `describe_column` re-reads the source file's mtime/size and downgrades `_meta.verdict.state` to
  `degraded` with `channels.index: "stale"` when it changed. Read that as "these stats describe a
  file that no longer exists in this form" and re-index before trusting them — the numbers are
  returned either way.
- **Schema safety:** `check_column_drop_safe` before any column drop (fuses PK/FK/runtime signals); `get_schema_impact` for transitive blast-radius of a schema change; `get_schema_drift` to compare two indexed dataset versions.
- **Discovery:** `find_similar_columns` for cross-dataset column dedup; `suggest_joins` for FK candidates; `find_unused_columns` (requires `ingest_sql_log` runtime data); `get_session_stats` for token savings.
- **Absence:** `search_data` carries the same verdict contract as jcodemunch — a non-`ok` state means the scan could not answer, not that the data is missing. Re-query or widen scope before concluding absence.
- **`search_data`'s rewrite probe no longer trips on its own write** (v1.31.11, verified against
  installed 1.31.12 at `tools/search_data.py:224`, `verdict.py:164-170`). The FIRST semantic search
  of a dataset lazily embeds and persists into `data.sqlite`; the mtime probe used to sample after
  that write, so a zero-result query came back `degraded` ("absence is NOT proven") and the identical
  second query `absent`. The probe now samples before the scan — so a first-search `degraded` you
  learned to re-run is now the `absent` it always should have been. Two shape changes: `_meta.rewrite_probe`
  rides every response (a rebuild starting mid-scan is not visible), and a real rewrite is
  `degraded` with `channels.index: "rebuilding"` and an `index_rewritten` note ("re-run once the write
  settles") — do not parse the degraded note for the embedding-channel wording; the note is now keyed
  on cause, and only the semantic-channel cause still carries the old text.
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
- **`verify_index` no longer counts an unhashed section as clean** (v1.136.1 / jdoc#33, verified
  against installed 1.136.1 at `tools/verify_index.py:163-183`). A section with a real byte range
  but an empty stored `content_hash` compared equal and landed in `clean_count`; it now goes to
  `skipped_sections` with reason `no_stored_hash`. **Gate CI on `drift_count == 0` AND
  `skipped_count == 0`** — on drift alone, "we could not check it" reads as "we checked it and it
  was fine", which is the one failure this tool exists to prevent. Latent rather than observed:
  every shipped parser routes through `compute_content_hash()`, which returns the sha256 of the
  empty string rather than `""`, so no current producer emits the empty case — but
  `Section.content_hash` defaults to `""`, so one producer returning early reintroduces it.
  Counters still sum to `section_count`. (Unchanged and worth restating: the default
  `source="cache"` verifies the indexed mirror and is NOT evidence the source is current — pass
  `source="live"` for that, and read `_meta.verify_layer` rather than inferring which bytes were
  compared.)
- **`doc_list_repos` decides sidecar-vs-index by SUFFIX now, and one legacy naming stops being
  listed** (v1.135.0 / jdoc#121, verified at `storage/doc_store.py:1699,1735`). The win is cost —
  orphaned sidecars left by a pre-1.108.0 `delete_index` were json-parsed in full only to return
  no row at all (1,093 files / 2.0 GB opened per call). The row shape is unchanged. But a
  **pre-jdoc#77 index whose repo name ends in `.summary` / `.terms` / `.related` /
  `.boilerplate` / `.duplicates`** has no summary sidecar to vouch for it and is no longer
  listed; upstream records this rather than solving it, because telling it from an orphan needs
  the parse being removed. A repo genuinely named e.g. `api.related` is readmitted via its own
  `.summary.json`. Read a repo missing from `doc_list_repos` as `degraded`, not absent — address
  it by handle or re-index it.
- **`index_local` needs explicit paths as of v1.130.0.** An argless refresh no longer widens the
  corpus, so newly added directories are not picked up unless you pass `paths=`. A refresh that
  silently shrinks the corpus looks identical to a successful one; check `corpus_selection_changed`
  and the `deleted` count in the result before trusting it.
- **Dot-directory skipping is narrower than "all of them"** (v1.126.1, verified against installed
  1.133.0 at `tools/_constants.py:27-52`). Two corrections to what this file used to say:
  - `.github` is **allowlisted** — it is dotted and legitimately full of documentation, and
    skipping it would trade one silent omission for another.
  - The rule tests a single path **component**, and the root you point at is not a component of
    any walk-relative path. **A corpus that itself lives under a dotted directory — e.g.
    `~/.claude/projects/<slug>/memory` or `~/.uncle-j-memory` — is unaffected.** Only dotted
    directories *below* the root are pruned. There is an upstream test on exactly this, because
    getting it wrong empties such a corpus silently.
  Opt anything else back in with `include_dot_dirs=` by directory **NAME**, not path (unioned
  with the allowlist).
- **An ignored argument now degrades the absence verdict** (v1.124.1 / jdoc#104, verified at
  `server.py:2563`, `tools/_arg_contract.py:26`). jdocmunch mints citable `absent:<sha>` refs, so
  before this a call whose scoping argument was silently dropped could still reach `absent` and be
  cited as proof the target is not there — disclosure alone did not stop it. Consequence: absence
  claims you could previously mint may now come back `degraded`. That is the fix, not a
  regression; re-issue the call with a supported argument rather than citing the old ref.
- **The embedding worker is ON by default** as of v1.132.0 (`embeddings/worker.py:88`,
  `embeddings/provider.py:495-510`) — sentence-transformers runs out of process, with a fallback to
  in-process when the child cannot be spawned. What matters to callers is the failure shape: an
  embed failure **raises**, and `embed_sections` reads that as `embed_failed` and **preserves the
  existing sidecar**. It deliberately does not write empty vectors, because a list of empty vectors
  reads as "this corpus legitimately has none" — the jdoc#107/#109 data-loss shape. So a failed
  embed leaves stale-but-real vectors in place: read a weak semantic channel as `degraded`, not as
  evidence the corpus is unembedded.
- **v1.126.0's confidence change, ground-truthed against installed 1.133.0** (`retrieval/confidence.py:1-45`,
  `retrieval/verdict.py:37,289`). The scale was **always 0–1** — it was not renumbered. The defect
  was that `strength` read a raw score against a hardcoded BM25 curve regardless of scorer, so the
  same ranking scored 0.62 in lexical mode and 0.087 in hybrid. So: **BM25/lexical thresholds are
  byte-identical to v1.125.0 and were never wrong**; only hybrid/semantic moved, and those were
  understated. Documented anchors: `top1 ≈ 1.0` trust the top hit, `≈ 0.6` best of several similar,
  `< 0.4` ambiguous or uncovered — and 0.4 is `LOW_CONFIDENCE_THRESHOLD`, below which
  `build_verdict` refuses to back an absence claim. Still prefer comparing hits against each other;
  0.4 is the one absolute worth remembering. (This bullet previously said the old→new scale was
  unverified and that any old threshold was wrong. Both halves were too strong; corrected 2026-08-21.)
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
- **The vault syncs at session close**, via a second Stop hook registered in
  `/opt/proj/jaredrhod/.claude/settings.json` that calls `sync_memory.sh -opt-proj-jaredrhod 15`
  — so a vault note written this session is searchable at the end of it, not at 02:30. The one
  gap left: if a jaredrhod session and a stack-repo session close within seconds, one loses the
  sync lock and defers to the cron (logged as `sync skipped` in `state/memweave-sync.log`).
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
  ≥15%. **This instruction was a no-op before v1.108.282** — the dispatcher
  swallowed the caller's `format` argument. From .282 it reaches the tool, so
  large responses genuinely come back as MUNCH (`#MUNCH/1 tool=… enc=gen1`
  followed by `@n=` back-references and a `t,`-prefixed table). Parse that
  shape rather than assuming plain JSON; observed on `list_repos` against
  1.108.288.
- **⚠ Every `search_ast` call encoded to an empty table, in every language and for every preset,
  from v1.108.282 to v1.108.302** (#553; fixed in .303, verified against installed 1.108.303 at
  `encoding/schemas/search_ast.py`). The compact schema declared table key `results` / scalar
  `result_count` / meta `files_searched`; the tool has always returned `matches` /
  `total_matches` / `files_scanned`, so `response.get("results", [])` found nothing and the
  encoder emitted a header and no rows. **The bug window opens exactly where the bullet above
  closes** — .282 is when `format` started reaching the tool, which is when this policy's
  `format="auto"` instruction began triggering it. Consequence for us: **an empty
  `search_ast(category="security")` sweep run in that window is not evidence of a clean repo** —
  the pre-merge checklist above (`search_ast` + `get_dead_code_v2` + `get_untested_symbols`)
  should be re-run on .303+ before any absence claim resting on it is trusted. Encoding id is
  `sa1` → `sa2`; pattern-specific keys (`marker`, `value`, `callee`, `loop_depth`,
  `nesting_depth`) now ride in a JSON `details` column and are re-expanded on decode.
- The encoder now **fails closed when a producer emits a table under a key no schema declares**
  (#555, `encoding/schema_driven.py:98`) — it raises and the dispatcher falls back to plain JSON,
  so the rows survive on the wire. A large response arriving as JSON rather than MUNCH is that
  guard firing, not a `format` argument being ignored.
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

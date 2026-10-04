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
`$STACK_ROOT/.venv/bin/`; memweave runs under `$STACK_ROOT/.venv-memweave/`; serena,
context7, and duckdb are launched via `uvx`/`npx`. Registered commands are in
`$STACK_ROOT/mcp-clients/claude-code-mcp.json`.

**This file is the short policy.** Every tool, every version-specific caveat, and the
`file:line` evidence behind each rule below live in
**`$STACK_ROOT/docs/ROUTING-REFERENCE.md`**. Read the matching section there (via jdocmunch)
when a result surprises you or before relying on a tool not named here.

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
| "What did we decide / discuss / build before?"  | **memweave** (`memory_search`)    | `mw_search.py` CLI, then transcript |
| General web / news / current events             | WebSearch, WebFetch               | —                                 |
| Bulk, low-stakes grunt work (see below)         | **ask_local** (local Ollama)      | do it yourself                    |

If the first choice is unavailable, try the fallback and note it. Do **not**
reach for `Read`, `Grep`, `Glob`, or `Bash` on files that any of the above
tools can answer structurally.

**ask_local** (`scripts/ask_local/server.py`, Ollama in `/opt/docker/ollama`) hands work to a
~9B local model: `summarize_local` / `extract_local` on a file you'd otherwise read just to
skim (pass `path=`, so the content never enters your context), `ask_local` for first drafts
and classification. **Never for the final answer, code review, or anything where a wrong result
gets acted on — verify what it returns.** It refuses credential-like paths and only ever
returns `{"error": ...}` on failure, never raises. Each call is logged to
`state/ask_local.jsonl` (counts and latency only) so its value can be measured.

## The absence contract — applies to every munch tool

- **A zero-result scan is not proof of absence.** `_meta.verdict.state` distinguishes `absent`
  (scan covered the tree, found nothing) from `degraded` (stale, partial, truncated,
  mid-rebuild). Only `absent` licenses "this does not exist"; on anything else, re-index and
  re-query first. Treat a bare empty result as `degraded`.
- `low_confidence` is not `absent` — results were returned. **0.4** is the one absolute
  confidence worth remembering: below it no tool will back an absence claim. Otherwise compare
  hits against each other.
- An ignored or unsupported argument degrades the verdict (jdocmunch). Re-issue the call;
  don't cite the old `absent:` ref.

## Operating rules

### 1. Code work — jCodeMunch first, Serena for LSP-hard questions

**Setup & orientation**
- `list_repos` / `resolve_repo` before any search; on a miss `index_folder`. `resolve_repo`
  stops at a nested independent clone — pass `repo` explicitly for the outer one.
  `CODE_INDEX_PATH` moves the whole index root; an index built under another value is
  simply not found (`degraded`, never `absent`).
- Unfamiliar repo: `plan_turn`, then `get_repo_map` / `suggest_queries`. Familiar repo:
  `digest`. Analysis session: `get_repo_health` first.
- Never `Read` a source file to "see what's in it" — `get_file_outline`, `search_symbols`,
  `get_file_content`, `get_symbol_source` (one id or an array), `get_context_bundle`,
  `get_ranked_context` ("how does X work" in one budgeted call), `assemble_task_context`.
- `search_text` for strings/comments/config (`context_lines` like `grep -C`); `winnow_symbols`
  for multi-constraint queries.
- Also: `index_file` (surgical re-index after an edit), `get_session_snapshot` (after
  compaction), `index_dependency` (the *installed* version's source — prefer over context7
  when the exact API matters), `check_embedding_drift`.
- `_meta` reaches you on this host (`meta_fields: null`); on a default install
  (`meta_fields: []`) it is stripped, so only body-level keys survive.
- **Freshness:** `get_watch_status` → read `index_freshness` (`fresh`/`stale`/`unknown`/
  `not_tracked`); gate on `any_stale is False` **and** `any_freshness_unknown is False`. The old
  `index_stale` key is gone — code keyed on it reads a missing key as fresh.
- **After a stack upgrade, re-index in full** (`invalidate_cache` then `index_folder`) before
  trusting symbol counts, `parent`, member lists, or stored ids — several git upgrades moved
  ids or added symbols without forcing a re-parse. A symbol-count jump after re-index is the
  fix, not a regression — so is a file-count drop from newly skipped build dirs
  (`discovery_skip_counts`). A not-found error may carry `near_miss_ids`; re-issue with one.
- If `JCODEMUNCH_EMBED_MODEL` ever changes, re-embed every repo (`embed_repo`); a mixed-width
  store silently drops vectors. `embed_repo` returning `all_batches_failed: true` embedded
  nothing, even though it exited clean.

**Reading results**
- `identity_type` grades `exact` / `normalized` / `prefix` / `segment` — accept `normalized`
  too; filtering on `exact` drops real hits.
- `kind` enum: `function`, `class`, `method`, `constant`, `type`, `template`, `import`,
  `field`, `property`, `variable`. Mutable state is `variable`/`property`/`field`, not
  `constant`.
- Semantic/hybrid search: a nonzero `skipped_dim_mismatch` means a partial corpus; a
  `semantic_topup` block means part of the ranking is lexical-only; a semantic channel of
  `unavailable` (with `semantic_channel_error`) is a failure, not "no embeddings".

**References & call graph**
- "Where is this name used?" → `check_references` (every use: imports + content mentions;
  content hits are capped by `max_content_results`, default 20 — raise it before concluding).
  `find_references` answers only who imports/re-exports it. `find_importers` — which files
  import a file. `get_call_hierarchy`, `get_impact_preview`, `get_blast_radius`.
- Type resolution, interface dispatch, "all callers across files" → **serena**.
- An empty `find_importers` / blast radius carrying `dynamic_import_boundary` or
  `dynamic_imports_unfollowed` is **not** evidence nothing loads the file.

**Before changing code** — `get_blast_radius` **and** `check_edit_safe` (complementary);
`check_rename_safe` before renames, `check_delete_safe` before deletes, `plan_refactoring` for
multi-file moves, `register_edit` after edits. Verdicts that are **not** green lights:
- `check_delete_safe`: `name_not_searchable`, `corpus_inadequate`, `dynamic_import_boundary`
  are refusals — never terminal; each carries a `would_change_verdict` gap to act on.
  `dynamic_import_boundary` also replaces `internal_only` and `test_coverage_only`.
- `check_edit_safe`: `dynamic_import_boundary` replaces `safe_to_edit` (confidence ≤ 0.6).
- `check_rename_safe.safe` is tri-state — `None` means unresolved (`unresolvable` says why);
  `if not r["safe"]` reads it as unsafe, `is not False` as safe. Handle it explicitly.
- Anything switching on `safe_to_delete` / `safe_to_edit` must handle these, or it reads a
  refusal as a green light.

**Quality & risk** (`get_hotspots`, `get_file_risk`, `get_dead_code_v2`, `get_untested_symbols`,
`search_ast`, architecture tools — catalog in the reference)
- **An empty `find_dead_code` is often a refusal**: gate on `signal_warning` and the
  `corpus_adequacy` block; fix by re-indexing, not by lowering `min_confidence`.
- `get_repo_health` `radar.composite`/`grade` and `get_architecture_metrics`
  `bytes_per_file` can be `null` — None-check before comparing.
- `get_churn_rate`: a missing target is an `error`; check it before reading `commits`.
  Shallow clones: `churn_measurable: false` means the churn number is not real.
- `get_untested_symbols.untested_count` is repo-wide; the page length is `returned_count`.
- Pre-merge gate: `search_ast(category="security")` + `get_dead_code_v2` +
  `get_untested_symbols`.

**Session & tier** — `set_tool_tier`: read `changed`, not `ok` (a narrowing that doesn't pay
for itself is refused with `ok: true`). Widening is never refused. `finalize_handoff` closes
an audit; it validates every evidence ref against what this session retrieved.

### 2. Data work — jDataMunch for CSVs, DuckDB for real SQL
- CSV/TSV: `describe_dataset` → `get_rows` with filters → `aggregate`. Never dump the file.
  `plan_query` + `run_sql` for single-dataset SQL; `get_dataset_health` before deep analysis.
- Parquet, JSON, remote data, or joins across sources → **duckdb**.
- `describe_column` / `search_data` verdicts follow the absence contract; a
  `channels.index: "stale"` profile describes a file that has since changed — re-index.
- `check_column_drop_safe` before dropping a column; `get_schema_impact` for blast radius.

### 3. Docs work — jDocMunch (mine), Context7 (theirs)
- Ask for sections by heading, not whole files: `search_sections`, `search_titles`,
  `get_section`, `get_document_outline`, `describe_section`, `get_section_context`.
- **`index_local` needs explicit `paths=`**; an argless refresh won't pick up new directories.
  **`truncated: false` ≠ everything indexed — read `coverage_complete`** and `skip_counts`.
  The `changes` list is capped; the `deleted` count is the authority. Check
  `corpus_selection_changed` — a silently shrunk corpus otherwise looks like success.
- Merely installing `fastembed` switches an unconfigured host's embedding provider; any model
  other than `all-MiniLM-L6-v2` forces a full re-embed.
- `verify_index`: gate on `drift_count == 0` **and** `skipped_count == 0`; default
  `source="cache"` doesn't prove the source is current (use `source="live"`).
- A repo missing from `doc_list_repos` is `degraded`, not absent. `has_embeddings: false`
  means word-only search.
- Dotted dirs below the index root are skipped (except `.github`); opt in with
  `include_dot_dirs=` by name. A root that is itself dotted is unaffected.
- Third-party library docs → **context7**, whenever a named library is involved.

### 4. Memory — memweave before WebSearch or re-asking
- Start every non-trivial task with a memory search for prior work: **`memory_search`**
  (MCP, ranked hits with path + line span), then **`memory_read`** for the context around a
  hit. Both are read-only; `memory_read` is confined to the corpus.
- Fallback when the MCP server isn't registered: the CLI, from inside the stack repo
  `.venv-memweave/bin/python scripts/memweave/mw_search.py "query" --k 5` (`--json`,
  `--min-score N`). A missing/empty store returns `no_index` (MCP) or exits nonzero (CLI) —
  fall back to the session transcript.
- The store at `~/.uncle-j-memory` is **cross-project**: transcripts from every project
  (what was *said*) plus a mirror of the Obsidian vault (what was *decided*). Search it
  whatever project you're in.
- **Never edit `memory/vault/` — edit the vault at `/opt/proj/jaredrhod/vaults/brain`.**
  The mirror excludes `11 - Personal` and `12 - Archive` and fails closed on unknown folders.
- Freshness: the nightly 02:30 cron covers every project; the session-end Stop hooks cover
  only the stack repo and the jaredrhod vault. Other projects' work is searchable after 02:30.

### 5. Runtime traces (when available)
- After `import_runtime_signal`: `find_hot_paths`, `find_unused_paths`, `get_runtime_coverage`.
  Skip them when no traces were ingested.
- A `diagnostics` block that is **absent** means no checker ran — never read it as clean.

### 6. Verification step
- Before finalizing code changes: `get_changed_symbols`, `get_untested_symbols`,
  `get_pr_risk_profile`. Report the risk score.
- An empty changed-symbol list means "nothing changed" only when `symbol_diff_complete` is
  true; an empty blast means "no impact" only when `absence_refused` is false.

### 7. Format economy
- Pass `format="auto"` on jcodemunch calls that may return a lot; parse the MUNCH shape
  (`#MUNCH/1 …`, `@n=` back-refs, `t,` rows) when it comes back. A large response arriving
  as JSON is the encoder failing safe, not the argument being ignored.
- An empty `search_ast` result from v1.108.282–.302 is not evidence of a clean repo — re-run.
- `get_ranked_context(compress=True)` fits more per budget; `get_symbol_source(verify=True)`
  when you need `content_hash`.

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

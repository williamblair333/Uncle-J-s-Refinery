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
- Start with `search_symbols`, `get_file_outline`, `get_repo_outline` for
  orientation. Never `Read` a source file to "see what's in it."
- Before editing a function, call `get_symbol_source` for that function, not
  `Read` on the whole file.
- Before committing to a change, call `get_blast_radius` to see what else
  breaks. For PRs, `get_pr_risk_profile` produces a single composite score.
- For type resolution, interface/trait dispatch, or "find all callers across
  files," prefer **serena** — its LSP backing outperforms AST-only search on
  Python/TS/Rust/Go/C#.
- Use `plan_turn` as your opening move on an unfamiliar repo. It respects
  the turn budget and selects the right tool for you.
- Use `winnow_symbols` when you have multiple constraints (kind + complexity
  + decorator + churn + importance). One call instead of five.

### 2. Data work — jDataMunch for CSVs, DuckDB for real SQL
- For any CSV / TSV: `describe_dataset` first, `get_rows` with filters next,
  `aggregate` for group-bys. Do **not** dump the file into context.
- For Parquet, JSON, remote data (S3 / GCS / R2), or anything involving
  joins across multiple sources, call **duckdb** directly — it runs real
  SQL in-process.
- For correlations: `get_correlations`. For cross-dataset work:
  `join_datasets`.

### 3. Docs work — jDocMunch (mine), Context7 (theirs)
- For project docs, runbooks, and internal markdown: **jdocmunch**. Ask for
  sections by heading, not whole files.
- For third-party library docs (FastAPI, React, Django, etc.), **context7**
  is authoritative and version-pinned. Call it whenever the question
  references a named library.

### 4. Memory — mempalace before WebSearch or re-asking
- Start every non-trivial task with a `mempalace` search for prior work on
  the same topic. "Have we solved this before?" is always question #1.
- On session close (or before compaction), snapshot the session into
  MemPalace so the next session starts with context.
- Organize mines by wing (person/project) so scopes stay tight.

### 5. Verification step
- Before finalizing code changes, run a verification pass using
  `get_changed_symbols` (git diff → symbols touched),
  `get_untested_symbols`, and `get_pr_risk_profile`. Report the risk score
  to the user.

### 6. Format economy
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

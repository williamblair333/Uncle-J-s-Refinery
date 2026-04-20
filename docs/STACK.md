# Stack reference

One-page-per-tool reference. See `../CLAUDE.md` for the routing policy
and `../README.md` for install/uninstall.

---

## jCodeMunch (primary code retrieval)

**What it does.** Tree-sitter parse + symbol index + byte-precise
retrieval for 70+ languages. Replaces "Read the whole file to find one
function" with "fetch exactly this symbol."

**Typical tools.** `search_symbols`, `get_symbol_source`,
`get_file_outline`, `get_repo_outline`, `find_references`,
`get_blast_radius`, `find_dead_code`, `get_untested_symbols`,
`get_changed_symbols`, `get_symbol_importance` (PageRank on imports),
`get_hotspots`, `get_dependency_cycles`, `get_pr_risk_profile`,
`plan_refactoring`, `search_ast`, `winnow_symbols`, `plan_turn`.

**Reported efficiency.** ~95% aggregate reduction vs brute-force reading
across public benchmark repos (Express, FastAPI, Gin). A/B test on a Vue
3 production codebase: 80% task success vs 72% native, 10.5% cache-token
reduction.

**Source here.** `../../jcodemunch-mcp-main/` — full whitepaper at
`jcodemunch_whitepaper.pdf`.

---

## jDataMunch (primary tabular retrieval)

**What it does.** Indexes CSV / tabular files into SQLite once, then
serves column profiles, filtered rows, server-side aggregations, joins,
and pairwise correlations.

**Typical tools.** `describe_dataset`, `get_rows`, `aggregate`,
`join_datasets`, `search_data`, `get_correlations`.

**Reported efficiency.** 255 MB / 1 M-row LAPD CSV: 111 M tokens paste
vs ~3,849 tokens via `describe_dataset`. Claimed 25,333x reduction on
that benchmark.

**When to prefer DuckDB instead.** Parquet, JSON-lines, remote object
storage (S3/GCS/R2), heavy SQL, cross-source joins.

**Source here.** `../../jdatamunch-mcp-master/`.

---

## jDocMunch (primary docs retrieval — your docs)

**What it does.** Indexes documentation by heading hierarchy, retrieves
specific sections by byte offset instead of serving whole files.

**Efficiency claim.** Finding a config section drops ~12k tokens to
~400. Browsing structure: ~40k to ~800.

**Use when** the docs in question are yours — repo READMEs, runbooks,
onboarding docs, internal wikis exported as markdown.

**Do NOT use for** third-party library docs — reach for Context7 there.

**Source here.** `../../jdocmunch-mcp-master/` — whitepaper PDF in the
same folder.

---

## MemPalace (primary long-term memory)

**What it does.** Verbatim storage of conversation / project content
with semantic search. Organized as wings (people / projects) -> rooms
(topics) -> drawers (content). Pluggable backend (default: ChromaDB).

**Performance.** 96.6% R@5 on LongMemEval raw (no LLM). 98.4% on the
held-out hybrid v4 pipeline. Leads Mem0 (~85%), Zep/Graphiti (~85%).
Zero API calls in the raw pipeline.

**Key commands.**
```
mempalace init <project-path>
mempalace mine <project-path>
mempalace mine ~/.claude/projects/ --mode convos    # ingest Claude sessions
mempalace search "why did we switch to GraphQL"
mempalace wake-up                                    # hydrate new session
```

**Source here.** `../../mempalace-develop/`.

---

## Serena (LSP-grade code intelligence — second opinion)

**What it does.** Same niche as jCodeMunch but backed by real Language
Server Protocol servers, not just AST. Wins on cross-file type
resolution, generics, interface/trait dispatch in Python, TypeScript,
Rust, Go, C#.

**Invocation.** `uvx --from git+https://github.com/oraios/serena serena start-mcp-server --context ide-assistant`

**When to reach for it over jCodeMunch.** "Find every caller of this
interface method across the repo" type questions, especially in typed
languages.

**Tradeoff.** Startup is slower (spins up real LSP servers); jCodeMunch
queries are cheaper per call.

---

## Context7 (third-party library docs)

**What it does.** Up-to-date, version-pinned docs for ~30,000+
libraries. Fed from llms.txt, OpenAPI specs, and websites.

**Invocation.** `npx -y @upstash/context7-mcp` (requires Node 18+).

**API key.** Optional; free key at https://context7.com/dashboard
lifts rate limits.

**Always use when** the question mentions a named library or framework
(FastAPI, React, Django, pandas, etc.) — Context7's docs are newer than
any training cutoff.

---

## DuckDB / MotherDuck MCP (heavy data — SQL over anything)

**What it does.** Run DuckDB SQL against CSV / Parquet / JSON / S3 / GCS
/ R2 / MotherDuck cloud, in-process, no server to manage.

**Invocation.**
```
# In-memory (default, safe):
uvx mcp-server-motherduck --db-path :memory: --read-write --allow-switch-databases

# Local DuckDB file:
uvx mcp-server-motherduck --db-path /absolute/path/to/db.duckdb

# MotherDuck cloud:
uvx mcp-server-motherduck --db-path md: --motherduck-token $MOTHERDUCK_TOKEN --read-write
```

**Use when** the question needs real SQL, joins across files, Parquet,
remote object storage, or analytics that jDataMunch's fixed verbs can't
express.

---

## How they fit together

```
   ┌──────────────────────────────────────────────────────────────┐
   │                     Your request                             │
   └─────────┬────────────────┬────────────────┬─────────────────┘
             │                │                │
    "code question"   "data question"   "docs question"   "what did we decide?"
             │                │                │                 │
     ┌───────▼─────┐   ┌──────▼────┐    ┌─────▼────┐     ┌──────▼──────┐
     │ jCodeMunch  │   │ jDataMunch│    │jDocMunch │     │  MemPalace  │
     │   (AST)     │   │  (CSV)    │    │(your docs)│    │(verbatim mem)│
     └─────┬───────┘   └─────┬─────┘    └────┬─────┘     └──────┬──────┘
           │ fallback        │ heavy SQL      │ 3rd-party        │
     ┌─────▼─────┐      ┌────▼─────┐     ┌────▼─────┐            │
     │  Serena   │      │  DuckDB  │     │ Context7 │            │
     │   (LSP)   │      │ (Mother- │     │ (Upstash)│            │
     │           │      │   Duck)  │     │          │            │
     └───────────┘      └──────────┘     └──────────┘            │
                                                                 │
                       Hook layer (PreToolUse / PostToolUse /    │
                       PreCompact) enforces "don't Read large    │
                       files; snapshot session on compact."      │
                                                                 │
                                   Native Read/Grep/Bash ◄───────┘
                                   (last resort only)
```

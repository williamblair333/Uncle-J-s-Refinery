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

**ChromaDB version pin.** `pyproject.toml` pins `chromadb==1.5.8` + `chroma-hnswlib==0.7.6`. The `chroma-hnswlib` package is critical — without it, chromadb falls back to Rust HNSW bindings with a type-confusion corruption bug (chroma-core/chroma#4460). All mine/repair scripts also export `CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI`. Do not bump chromadb without verifying a clean repair run.

**SQLite version pin.** The uv-managed Python 3.11 statically embeds SQLite 3.50.4, which has a WAL-reset data race bug (present since SQLite 3.7.0, fixed in 3.51.3). `install.sh` step 2b builds `pysqlite3` from source against the SQLite 3.51.3 amalgamation and installs a `.pth` file in venv site-packages that swaps `stdlib sqlite3 → pysqlite3` at every process startup. Verify with: `.venv/bin/python3 -c "import sqlite3; print(sqlite3.sqlite_version, sqlite3.__name__)"` — should print `3.51.3 pysqlite3`.

**turbovecdb (parallel eval — not production).** `turbovecdb==0.1.0` + `turbovec==0.7.0` installed from `williamblair333/turbovecdb@fix/security-findings` (commit `cf5eb6c`) via `uv pip`. Lives at `~/.turbovecdb-eval/` — completely separate from `~/.mempalace/`. ChromaDB stays production. Re-install via `bash scripts/turbovecdb-install.sh` (idempotent, called by `install-reliability.sh`).

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

---

## Dreaming (scheduled session synthesis)

**What it does.** Runs on a schedule (default: 2 AM daily). Queries Langfuse
for traces since the last run, invokes the `dream-synthesizer` skill to
extract recurring mistakes and proven playbooks, and writes the results to
MemPalace (wing: `dreaming`) and `~/.claude/CLAUDE.md`.

**Entry point.** `features/dreaming/dream.sh` (also available as `/dream`
slash command for on-demand runs inside Claude Code).

**Install.**
```bash
bash features/dreaming/install.sh
```

**When to use.** After a project has accumulated 10+ Langfuse traces. The
`prior-art-check` skill will automatically surface dreaming output on the
next non-trivial task because it queries MemPalace, and the `## Dreaming
Notes` section in `CLAUDE.md` informs every session directly.

**Key env vars.** `DREAMING_CRON_SCHEDULE` (default: `0 2 * * *`),
`DREAMING_ENABLED` (default: `1`). Set in `state/dreaming.env`.

---

## Orchestrator + Multi-agent (--decompose mode)

**What it does.** When `ralph-harness.sh --decompose` is set, the orchestrator
skill decomposes the PRD into a JSON task manifest, bash spawns one
`claude -p` subprocess per task (in parallel where safe), and a synthesis
agent merges the outputs. Traces are tagged by `role:` in Langfuse.

**Roles and tool mapping:**

| Role | Designated tools |
|---|---|
| `code` | jCodeMunch, Serena |
| `data` | jDataMunch, DuckDB |
| `docs` | jDocMunch, Context7 |
| `memory` | MemPalace |
| `general` | all tools |

**AGENT_ROLE env var.** Set by ralph-harness.sh on each sub-agent subprocess.
Langfuse traces carry `role:<value>` tags so multi-agent runs appear as a
role-tagged tree rather than an undifferentiated stream.

**Usage.**
```bash
./ralph-harness.sh --prd ./PRD.md --decompose --rubric ./.claude/outcomes/rubric.md
```

**Composition with Outcomes.** When both `--decompose` and `--rubric` are
set, the synthesized output is evaluated by the outcomes grader after each
iteration. The grader runs in a fresh context and checks the rubric. Loop
exits only when synthesis + rubric both pass.

**Guardrail invariants.** Sub-agents inherit `MCP_TIMEOUT=60000` via env.
jCodeMunch PreToolUse/PostToolUse hooks fire per sub-agent (they are global
settings, not session-local). The bash-matcher destructive-command blocks
apply to every subprocess — `--decompose` does not bypass them.

---

## Session Stats (weekly efficiency reporter)

**What it does.** Runs on a schedule (default: every Sunday 8 AM). Queries Langfuse
for the past 7 days of traces, groups them by date + project, and renders a markdown
table with trace count, tool calls, token usage, and a `⚠ high` flag for sessions
exceeding 40k tokens.

**Entry point.** `features/session-stats/stats.sh` (also available as `/stats`
slash command for on-demand runs inside Claude Code).

**Output (--cron mode).**
- `~/.claude/dreaming-output/stats-YYYY-MM-DD.md` — picked up automatically
  by the next dreaming run so weekly stats appear in MemPalace playbooks.
- `state/stats-weekly.md` — human reference; symlink-friendly for dashboards.

**Install.**
```bash
bash features/session-stats/install.sh
```

**Manual trigger.**
```bash
bash features/session-stats/stats.sh [--days N]
```

**Key env vars.** `STATS_CRON_SCHEDULE` (default: `0 8 * * 0`),
`DREAMING_OUTPUT_DIR` (default: `~/.claude/dreaming-output`).
Set in `state/session-stats.env` (written by install.sh).

---

**SubagentStart hook audit (2026-05-14):** A SubagentStart hook IS configured
in `~/.claude/settings.json`, invoking
`jcodemunch-mcp hook-subagent-start` on every sub-agent spawn. This hook
injects a condensed repo orientation into the sub-agent's context (per the
jcodemunch `--help` description: "SubagentStart hook: inject condensed repo
orientation"). Tool scoping per role is additionally enforced via the
sub-agent's task prompt (the `task` field from the orchestrator manifest).
The routing instructions in the task prompt remain the authoritative
mechanism for restricting which tools a given role should use; the
SubagentStart hook supplements orientation but does not selectively disable
MCP servers (Claude Code's current architecture does not support
per-session MCP server disable).

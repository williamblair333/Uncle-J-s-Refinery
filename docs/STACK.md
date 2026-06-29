# Stack reference

One-page-per-tool reference. See `../CLAUDE.md` for the routing policy
and `../README.md` for install/uninstall.

---

## jMunch Console (optional browser GUI)

**What it does.** Local browser control panel for the jMunch MCP suite.
Surfaces indexed repos, live token-savings counter, Claude Code sessions
browser (with resume), MCP process control, jcm config editor, and
log/diagnostic tails — all at `http://127.0.0.1:8765`.

**How to start.** `bash scripts/jmunch-console.sh` (passes `JMUNCH_MCP_BIN`
to the venv binary; optional port arg). Stop with Ctrl-C.

**Update.** `git -C review/jmunch-console pull`
Surfaced automatically by `scripts/check-stack-freshness.sh`.

**Key panels.**
- *Index & Watcher* — repo cards: symbol/file counts, freshness, watcher state.
- *Savings* — live lifetime counter (polls `~/.code-index/_savings.json` every 4s) + 30d receipt breakdown.
- *Sessions* — browse/resume past Claude Code sessions by repo.
- *Processes* — live jcm server PIDs; kill/observe without hunting `ps`.
- *Config* — typed GUI editor for `config.jsonc` (all keys, grouped, save/reset).
- *Diagnostics* — tails `jcw_*.log` watcher logs + `_session_live.json` heartbeat.

**Phase 1 (current).** GET-only, `127.0.0.1`-only (hardcoded), no auth required by
default. Mutations (config write, launch, session resume) behind `ALLOW_LAUNCH`
which requires `JMUNCH_CONSOLE_READ_ONLY` to be unset — off by default.

**Not yet wired.** healthcheck.sh entry (deferred until stable over a few sessions).

**Source.** `review/jmunch-console/` (nested git repo; outer tree ignores its contents).
MIT licensed. Upstream: `github.com/jgravelle/jmunch-console`.

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

## memweave (primary long-term memory)

**What it does.** Offline, cross-project memory. Exports your Claude Code
session corpus and project content into a markdown corpus and indexes it
for local semantic search. **Not an MCP server** — a Bash CLI plus a small
Python search tool. No external service, no API calls, fully offline.

**Store location.** `~/.uncle-j-memory` — the markdown corpus and its
local index. The store is fully rebuildable from the corpus, so a wiped
index is recoverable with one sync run; there's no separate backup step.

**Key commands.**
```bash
# Build / refresh the store (full cross-project export + index):
bash scripts/memweave/sync_memory.sh --all

# Search the store (read-only; --json for machine-readable output):
.venv-memweave/bin/python scripts/memweave/mw_search.py "why did we switch to GraphQL" --k 5
```

**Freshness is automatic.** The `uncle-j-memweave-sync` nightly cron (02:30)
plus a session-end Stop-hook keep the store current — you don't need to run
`sync_memory.sh` by hand.

**Source here.** `scripts/memweave/` — `sync_memory.sh` (build),
`mw_search.py` (search), plus the export/index helpers.

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
     │ jCodeMunch  │   │ jDataMunch│    │jDocMunch │     │  memweave   │
     │   (AST)     │   │  (CSV)    │    │(your docs)│    │(offline mem) │
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
the memweave store and `~/.claude/CLAUDE.md`.

**Entry point.** `features/dreaming/dream.sh` (also available as `/dream`
slash command for on-demand runs inside Claude Code).

**Install.**
```bash
bash features/dreaming/install.sh
```

**When to use.** After a project has accumulated 10+ Langfuse traces. The
`prior-art-check` skill will automatically surface dreaming output on the
next non-trivial task because it runs `mw_search.py` (memweave), and the `## Dreaming
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
| `memory` | memweave |
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
  by the next dreaming run so weekly stats appear in memweave playbooks.
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

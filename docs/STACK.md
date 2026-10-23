# Stack reference

One-page-per-tool reference. See `../CLAUDE.md` for the routing policy
and `../README.md` for install/uninstall.

---

## MCP registration (and the Windows variant)

On Linux the servers are registered through `install.sh` / `claude mcp add`
(user scope). On the Windows host they are registered by a **machine-local,
gitignored** project-scoped `.mcp.json` at the repo root — one-time setup
`cp scripts/win/mcp.json .mcp.json` — pinned to the venv binaries. The file
must never be committed: project scope shadows user scope per server name, so
a shared copy with `C:\...` paths kills all five stack servers on Linux.

| Server | Invocation | Note |
| ------ | ---------- | ---- |
| jcodemunch | `serve --transport stdio` | |
| jdatamunch | *(no arguments)* | bare invocation **is** the stdio server |
| jdocmunch  | `serve` | has the subcommand, **no** `--transport` flag |

**The three CLIs are not uniform.** Passing `--transport stdio` to jdatamunch or
jdocmunch makes them exit immediately; the only symptom is
`MCP error -32000: Connection closed`. Verify with `claude mcp list`, which prints
the resolved command — `claude mcp get <name>` no longer does.

Project scope means the servers are live only when Claude Code runs from this
repo, and that first run would normally raise a trust prompt; the three names are
pre-approved under `projects[<repo>].enabledMcpjsonServers` in `~/.claude.json`.

**Do not run `jcodemunch-mcp init` / `install claude-code` on this host.** It
registers via floating `uvx` (unpinning the stack), appends the Code Exploration
Policy to *global* `~/.claude/CLAUDE.md`, writes hooks into *global*
`~/.claude/settings.json`, and resolves "project" against the current working
directory rather than this repo.

`scripts/win/mcp.json` deliberately names `.venv\Scripts\*.exe` explicitly rather
than the `.venv/bin` compat symlink: Claude Code launches MCP servers via
`CreateProcess`, not through bash, so neither MSYS `.exe` suffixing nor the
directory symlink can be relied on there. Full detail in `WINDOWS-PORT.md`.

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
for local semantic search. Exposed two ways: an **MCP server**
(`scripts/memweave/mw_mcp.py`, run by `.venv-memweave`), which gives Claude `memory_search`
and `memory_read`, and the `mw_search.py` CLI as a fallback. `memory_read` only reads inside
the store. No external service, no API calls, fully offline.

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
`mw_search.py` (search CLI), `mw_mcp.py` (MCP server), plus the export/index helpers.

---

## ask_local (local model for bounded grunt work)

**What it does.** An MCP server that hands bounded subtasks to a local model, so Claude stays
in charge. Tools:

| Tool | What it does |
|---|---|
| `summarize_local` | Summarizes a file or block of text. It reads the file itself, so the content never enters Claude's context |
| `extract_local` | Extracts JSON that matches a schema |
| `ask_local` | Drafts and classification |
| `local_status` | Reports whether the backend is up |

It has no shell, writes no files, and refuses credential-like paths. Never use it for a final
answer.

**Starting it.**
```bash
just ask-local-up        # starts the backend config/ask_local.env names (heretic on this host)
just chat                # chat page at http://127.0.0.1:8091 (start/stop/logs, Claude/agy offload)
just heretic logs        # model logs; `just heretic down` stops it
curl -s 127.0.0.1:8090/health   # {"status":"ok"} when heretic is up
```

**Backend.** Ollama in Docker, from `docker/ollama/compose.yaml` in this repo. A host that
keeps its own `/opt/docker/ollama/compose.yaml` uses that one instead. It's bound to
`127.0.0.1:11434` only, unloads idle models after 10 minutes, and loads one model at a time.
The models live in `/opt/models/ollama` (falls back to `~/.local/share/ollama-models` when
`/opt` isn't writable). The default is `qwen3.5:9b`. `install.sh` runs `scripts/ollama-up.sh`,
which starts the container, adds the GPU overlay (`compose.gpu.yaml`) only when Docker has the
`nvidia` runtime, and pulls the default model. Skipped with `--skip-optional`.
```bash
bash scripts/ollama-up.sh                                  # start + pull default model
docker exec ollama ollama list                             # models
docker exec ollama ollama pull <model>                     # add one
```

**Speed depends on free VRAM.** With the model fully on an RTX 3060, a warm extraction takes
about 5 s, a summary about 9 s, and generation runs at about 51 tok/s. When other GPU work
holds VRAM, part of the model runs on the CPU and calls take about 60 s. A host with no GPU
runs it entirely on CPU: expect a minute or more per call and about 6 GB of RAM while the model
is loaded. A stopped container
is fine: calls return `ollama_unreachable`, and `healthcheck.sh` reports it without failing.

**Measuring it.** `state/ask_local.jsonl` gets one line per call, with counts and latency but
never content. Use it to decide whether ask_local earns its place.

**Config.** Optional environment variables: `ASK_LOCAL_BACKEND` (`ollama`, the default, or
`openai` for llama-server), `ASK_LOCAL_URL`, `ASK_LOCAL_MODEL`, `ASK_LOCAL_TIMEOUT` (default
300 s), `ASK_LOCAL_LOG` (set it to empty to disable the log).

**llama-server backend.** The main host runs Qwen3.6-35B-A3B Heretic this way:
`just heretic up -d` starts `docker/llama-heretic/compose.yaml` on 127.0.0.1:8090, and
ask_local reads `ASK_LOCAL_BACKEND=openai ASK_LOCAL_URL=http://127.0.0.1:8090
ASK_LOCAL_MODEL=heretic` from `config/ask_local.env`, so a reinstall keeps them.

---

## Speech (whisper.cpp speech-to-text, Chatterbox Nano cloned voices)

**What it does.** Two loopback-only Docker services, both CPU only, so they never touch the
GPU that Heretic and Ollama share. Lineup items #4 and #5
(`docs/proposals/2026-10-22-local-model-lineup.md`).

| Service | Port | Model (in `/opt/models`) | License | RAM |
|---|---|---|---|---|
| `whisper` (`docker/whisper/`) | 127.0.0.1:8092 | `whisper/ggml-large-v3-turbo-q5_0.bin` (574 MB) | MIT | ~0.8 GB |
| `chatterbox` (`docker/chatterbox/`) | 127.0.0.1:8093 | `chatterbox-nano/` (110M, ~2 GB on disk) | MIT, output watermarked | 4.3 GB idle, 5.4 GB peak |

**Starting it.**
```bash
just whisper up -d       # speech-to-text; `just whisper logs` / `just whisper down`
just tts up -d           # text-to-speech (first `up` builds the image, ~1.5 GB)
curl -s -F file=@clip.wav -F response_format=text 127.0.0.1:8092/inference
curl -s 127.0.0.1:8093/health    # {"model":"chatterbox-nano",...,"voices":[...]}
curl -s -X POST 127.0.0.1:8093/v1/audio/speech -H 'Content-Type: application/json' \
  -d '{"input":"Hello there.","voice":"librivox-gettysburg"}' -o out.wav
```
Both go through dcup. whisper takes wav, mp3, ogg or m4a (`--convert`), defaults to English,
and takes `language=auto` as a form field for other languages. For a cloned voice, drop a
clean 5–20 s clip in `/opt/models/chatterbox-voices/<name>.wav` and send `"voice": "<name>"`.
`librivox-gettysburg` (a LibriVox reader, public domain) is there as a test voice. The
built-in voice is `default`.

**Speed (measured 2026-10-23, Ryzen 5 5500, while other jobs loaded the host).** whisper: a
30 s clip takes 31 s at load ~11 and 42 s at load ~27, and the transcript was word for word.
That's slower than real time, so it's fine for dictation and files but not live captions.
Chatterbox: about 5 s per sentence (3 sentences, 11.6 s of audio, took 15.4 s). The first use
of a voice adds about 3 s. Speaker similarity to the reference clip, by Chatterbox's own voice
encoder, was 0.87 for the clone and 0.56 for the built-in voice. Samples are in
`/opt/outputs/speech/`. Under heavy load (~40) whisper took 252 s, so the numbers swing with
whatever else is running.

**Not the same as voice-line.** voice-line runs its own whisper-server and Kokoro on the GPU
(ports 2022 and 8880 in `/opt/proj/.port-registry`). These two services are separate from it.

---

## live_preview (watch any build in a browser)

`scripts/live_preview/server.py` runs on `.venv` and needs only the standard library plus
`mcp`. It's registered by `install.sh` as `live_preview`.

- **Tools:** `preview_publish`, `preview_watch`, `preview_stop`, `preview_status`.
- **Shell:** the same operations via `just preview publish|watch|status|list`.
- **Storage:** sessions live in `LIVE_PREVIEW_HOME` (default `~/.live-preview/<project>/<session>/`).
- **Origin:** the viewer and bundle format are vendored from HKUDS/CLI-Anything@34f5195;
  `scripts/live_preview/NOTICE` records what changed. CLI-Anything's own `cli-hub` isn't
  included, because it sends PostHog analytics by default.
- **First user:** the Partikus MCP server (`/opt/proj/partikus/partikus_mcp`, registered as
  `partikus`), which publishes a 4-view FreeCAD render per build step.

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

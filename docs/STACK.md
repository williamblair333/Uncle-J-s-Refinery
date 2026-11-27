# Stack reference

Use this reference to see what each tool does and when to reach for it. See `../CLAUDE.md` for the rules Claude follows when choosing tools and `../README.md` for setup and removal.

---

## MCP registration (and the Windows variant)

An MCP server gives an assistant tools it can call, such as a tool that fetches a function from your code. MCP stands for Model Context Protocol. It defines how the assistant and server talk to each other.

On Linux, `install.sh` uses `claude mcp add` to register the servers for your user account. On Windows, run `cp scripts/win/mcp.json .mcp.json` once from the repo root. The resulting `.mcp.json` points to the executables in the project's virtual environment, which keeps the tool versions tied to this setup.

**Keep that file local and out of Git.** This repo already ignores it. Claude Code uses the project's settings when the same server name appears in both places. If you commit the Windows file, Linux tries to launch all five stack servers from `C:\...` paths, and all five fail to start.

| Server | Invocation | Note |
| ------ | ---------- | ---- |
| jcodemunch | `serve --transport stdio` | |
| jdatamunch | *(no arguments)* | bare invocation **is** the stdio server |
| jdocmunch  | `serve` | has the subcommand, **no** `--transport` flag |

Each command-line tool has its own launch syntax. If you pass `--transport stdio` to jdatamunch or jdocmunch, it exits immediately. All you see is `MCP error -32000: Connection closed`. Use `claude mcp list` to see the command Claude Code will run. `claude mcp get <name>` no longer shows it.

Project scope means these servers run only when Claude Code opens this repo. The first run would usually ask you to trust them. This host already approves the three names under `projects[<repo>].enabledMcpjsonServers` in `~/.claude.json`.

**Do not run `jcodemunch-mcp init` / `install claude-code` on this host.** Those commands register an unpinned version through `uvx`. They also add the Code Exploration Policy to the global `~/.claude/CLAUDE.md` and write hooks to the global `~/.claude/settings.json`. Hooks are commands that run when an event occurs. The setup treats your current directory as the project, wherever you happen to run it.

`scripts/win/mcp.json` spells out the `.venv\Scripts\*.exe` paths. Claude Code launches servers with Windows' `CreateProcess`, not through Bash. So neither the MSYS `.exe` suffix nor the `.venv/bin` compatibility symlink can be relied on. See `WINDOWS-PORT.md` for details.

---

## jMunch Console (optional browser GUI)

Open `http://127.0.0.1:8765` to see what jMunch has indexed, resume a Claude Code session, or check running servers and their recent logs.

Start the console with `bash scripts/jmunch-console.sh` and press Ctrl-C to stop it. The script passes `JMUNCH_MCP_BIN` to the virtual environment's executable. You can also pass a port.

Update with `git -C review/jmunch-console pull`. `scripts/check-stack-freshness.sh` tells you automatically when an update is available.

- *Index & Watcher* shows how many files and symbols each repo has indexed, how fresh the index is, and whether the file watcher is running.
- *Savings* reads `~/.code-index/_savings.json` every 4s. It shows total token savings and a 30d breakdown. Tokens are the pieces of text a model reads or writes.
- *Sessions* lets you find and resume past Claude Code sessions by repo.
- *Processes* lists running jCodeMunch servers and their process IDs. You can inspect or stop them without looking them up in `ps`.
- *Config* groups the settings in `config.jsonc` and lets you edit, save, or reset them.
- *Diagnostics* shows the latest lines of the `jcw_*.log` watcher logs and the live status signal from `_session_live.json`.

**Phase 1 (current).** The console listens only on `127.0.0.1`, and that is fixed in the code, so only this machine can reach it. By default it accepts only GET requests, which read information, and requires no sign-in. To save settings, launch a process, or resume a session, enable `ALLOW_LAUNCH` and leave `JMUNCH_CONSOLE_READ_ONLY` unset.

There's no healthcheck.sh entry yet. It's on hold until the console has run reliably for a few sessions.

The MIT-licensed source lives in `review/jmunch-console/`, a separate Git repo inside this one. The outer repo ignores its contents. Upstream is `github.com/jgravelle/jmunch-console`.

---

## jCodeMunch (primary code retrieval)

Ask jCodeMunch for a function and it can return just that function. It uses Tree-sitter, a parser that breaks source code into meaningful parts, to build an index of named parts such as functions and classes. These are called symbols. The index lets it fetch the exact bytes for a symbol in 70+ languages.

**Typical tools.** `search_symbols`, `get_symbol_source`,
`get_file_outline`, `get_repo_outline`, `find_references`,
`get_blast_radius`, `find_dead_code`, `get_untested_symbols`,
`get_changed_symbols`, `get_symbol_importance` (PageRank on imports),
`get_hotspots`, `get_dependency_cycles`, `get_pr_risk_profile`,
`plan_refactoring`, `search_ast`, `winnow_symbols`, `plan_turn`.

**Reported benchmarks.** Across Express, FastAPI, and Gin, the project reports a ~95% aggregate reduction compared with reading files in full. In a comparison on a Vue 3 production codebase, task success was 80% with jCodeMunch vs 72% with native tools. Cache-token use fell by 10.5%.

The source is in `../../jcodemunch-mcp-main/`. See `jcodemunch_whitepaper.pdf` for the full report.

---

## jDataMunch (primary tabular retrieval)

jDataMunch loads a CSV or other table into SQLite, a database stored in a file. Once the data is indexed, you can ask for a few matching rows, a summary of a column, or a total by group. You can also join tables by a shared field or check how closely two columns vary together.

**Typical tools.** `describe_dataset`, `get_rows`, `aggregate`,
`join_datasets`, `search_data`, `get_correlations`.

**Reported benchmark.** Pasting a 255 MB LAPD CSV with 1 M rows took 111 M tokens. A call to `describe_dataset` used ~3,849 tokens. The benchmark reports a 25,333x reduction.

Reach for DuckDB when you need heavier SQL, joins across sources, Parquet or JSON-lines files, or files in remote storage (S3/GCS/R2).

The source is in `../../jdatamunch-mcp-master/`.

---

## jDocMunch (primary docs retrieval — your docs)

jDocMunch uses headings to map your docs. It records where each section starts in its file, so a request for a config section can return just that section.

The tool reports a drop from ~12k tokens to ~400 for finding a config section. Browsing the heading structure drops from ~40k to ~800.

Use it for your own READMEs, runbooks, onboarding guides, and internal wikis exported as Markdown. Don't use it for third-party library docs. Use Context7 for those.

The source and whitepaper PDF are in `../../jdocmunch-mcp-master/`.

---

## memweave (primary long-term memory)

Use memweave to search past sessions across all projects. It exports Claude Code sessions and project material as Markdown. Its local search matches by meaning, so you can find an old discussion without remembering its exact words.

Claude searches with `memory_search` and opens results with `memory_read`. The MCP server runs `scripts/memweave/mw_mcp.py` using `.venv-memweave`. When the MCP server isn't available, search from the terminal with `mw_search.py`. `memory_read` stays inside the store, and the whole system works offline.

`~/.uncle-j-memory` holds both the Markdown and the search index. If the index is wiped, one sync rebuilds it from the Markdown. The index needs no separate backup.

**Key commands.**
```bash
# Build / refresh the store (full cross-project export + index):
bash scripts/memweave/sync_memory.sh --all

# Search the store (read-only; --json for machine-readable output):
.venv-memweave/bin/python scripts/memweave/mw_search.py "why did we switch to GraphQL" --k 5
```

The `uncle-j-memweave-sync` job runs nightly at 02:30. A hook also updates the store when a session in this repo ends. Other projects catch up at 02:30. You don't need to run `sync_memory.sh` by hand.

In `scripts/memweave/`, `sync_memory.sh` builds the store, `mw_search.py` searches it from the terminal, and `mw_mcp.py` serves it to Claude. The folder also contains the export and indexing helpers.

---

## delegate (offload work to other models)

Use delegate to send a task to another model. `install.sh` registers `scripts/delegate/server.py` for your user account.

- `ask_agy` uses Gemini Flash by default. Pass `model=` to choose another model.
- `ask_heretic` uses the local model on port 8090.
- `ask_openai` works with any OpenAI-compatible API. Enable it by setting `OPENAI_API_KEY` and `DELEGATE_OPENAI_MODEL`.
- `make_image`, `make_video`, and `speak` reuse `scripts/local_chat`.
- `delegate_status`.

agy and OpenAI calls refuse requests when the session directory or a path in the prompt is a path listed in `config/delegate-local-only.txt` or `DELEGATE_LOCAL_ONLY`, or sits under one.

Settings come from environment variables, which are values passed to the running program. Set `DELEGATE_AGY_MODEL`, `DELEGATE_AGY_TIMEOUT`, `DELEGATE_OPENAI_URL`, `DELEGATE_OPENAI_KEY_ENV`, or `DELEGATE_LOG` as needed. Each call logs the service, model, duration in seconds, and success status to `state/delegate.jsonl`. Prompts and replies stay out of the log.

---

## ask_local (local model for bounded grunt work)

Claude can hand a small task, such as summarizing a file, to a model running on your machine. Claude stays in charge of the overall task.

| Tool | What it does |
|---|---|
| `summarize_local` | Summarizes a file or block of text. It reads the file itself, so the content never enters Claude's context |
| `extract_local` | Extracts JSON that matches a schema |
| `ask_local` | Drafts and classification |
| `local_status` | Reports whether the backend is up |

The server cannot run shell commands or write files. It refuses paths that look like they contain credentials. Keep the final answer with Claude.

**Starting it.**
```bash
just ask-local-up        # starts the backend config/ask_local.env names (heretic on this host)
just chat                # chat page at http://127.0.0.1:8091 (start/stop/logs, Claude/agy offload)
just heretic logs        # model logs; `just heretic down` stops it
curl -s 127.0.0.1:8090/health   # {"status":"ok"} when heretic is up
```

In the chat page, "Search the web" sends the model SearXNG's top 5 results and the text of the top 3 pages. SearXNG gathers results from other search engines. The chat page fetches only public addresses and checks again after each redirect.

"Think first" turns on Heretic's hidden reasoning. It helps with hard questions, but it can be minutes slower when it runs alongside Klarheit's 9B model. One web answer took 9 s without it and 375 s with it. "Speak replies" reads answers aloud through Chatterbox.

Type `/image <prompt>` to make an image (~1–2 min). The command starts and stops ComfyUI for you. Type `/video
<prompt>` for video (~8 min) or `/speak <text>` for speech. Results appear in the chat. The page serves media only from `/opt/outputs/comfyui` and `/opt/outputs/speech`. Spoken replies (`chat-*.wav`) expire after 7 days (`CHAT_SPEECH_DAYS`). Images, videos, and other speech files stay.

If web search finds nothing, the page shows an error naming the engines that refused. It doesn't let the model answer from memory. Google, Brave, DuckDuckGo, Startpage, and Qwant all block SearXNG after heavy use. You may see a CAPTCHA, "too many requests," or "access denied." SearXNG retries them later.

Mojeek and Yep use independent search indexes. Both were enabled on 2026-10-24 in `/opt/docker/searnx/searxng/settings.yml` (`disabled: false`, outside any repo) to keep results coming. Bing and Yahoo use Microsoft's index and stay off. Check which engines failed with `curl -s '127.0.0.1:8086/search?q=test&format=json' | jq '.unresponsive_engines'`.

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

**Speed depends on free VRAM, the memory on the graphics card.** With the whole model on an RTX 3060 and already loaded, extraction takes about 5 s and a summary takes about 9 s. The model generates text at about 51 tok/s.

If other work fills GPU memory, part of the model runs on the CPU and calls take about 60 s. A machine with no GPU runs the whole model on the CPU. Expect a minute or more per call and about 6 GB of RAM while the model is loaded. If the container is stopped, calls return `ollama_unreachable`. `healthcheck.sh` reports that status and still passes.

Each call adds a line to `state/ask_local.jsonl` with counts and elapsed time. The log leaves out the content. Use it to decide whether ask_local is worth keeping.

**Config.** Optional environment variables: `ASK_LOCAL_BACKEND` (`ollama`, the default, or
`openai` for llama-server), `ASK_LOCAL_URL`, `ASK_LOCAL_MODEL`, `ASK_LOCAL_TIMEOUT` (default
300 s), `ASK_LOCAL_LOG` (set it to empty to disable the log).

**llama-server backend.** The main host runs Qwen3.6-35B-A3B Heretic this way:
`just heretic up -d` starts `docker/llama-heretic/compose.yaml` on 127.0.0.1:8090, and
ask_local reads `ASK_LOCAL_BACKEND=openai ASK_LOCAL_URL=http://127.0.0.1:8090
ASK_LOCAL_MODEL=heretic` from `config/ask_local.env`, so a reinstall keeps them.

---

## Image and video generation (ComfyUI)

ComfyUI makes images and video on this machine. The Docker setup builds v0.39.0 locally from `docker/comfyui/Dockerfile`. It uses a pinned upstream commit and adds city96/ComfyUI-GGUF.

It listens only on `127.0.0.1:8188`. The `--offline` flag keeps the web interface offline, and the Hugging Face libraries run offline too. Both models use the Apache 2.0 license, which allows commercial use. The licenses were rechecked on Hugging Face on 2026-10-23.

| Job | Model | Files in |
|---|---|---|
| Image | Z-Image-Turbo (bf16, Qwen3-4B fp8 text encoder) | `/opt/models/z-image-turbo/` |
| Video | Wan 2.2 T2V A14B, GGUF Q4_K_M, lightx2v 4-step LoRAs | `/opt/models/wan2.2/` |

**Starting it.**
```bash
just comfy-models                 # download + sha256-check the models (~47 GB; skips verified files)
just image "a red fox in snow"    # → /opt/outputs/comfyui/image_NNNNN_.png  (--seed, --width, --height)
just video "a sailboat at dusk"   # → /opt/outputs/comfyui/video_NNNNN_.mp4  (--frames, default 81)
just comfy up -d / down           # only to keep it running between jobs (it builds on first run)
```
`just image` / `just video` start ComfyUI themselves when it's down (after any Klarheit wait)
and stop it when the job ends; `--keep-up` leaves it running, `--no-autostart` exits instead.
The web UI is at http://127.0.0.1:8188. `just image` / `just video` print the output path,
the wall time and the peak VRAM, then unload the models (`--keep-loaded` to skip that).

**Measured 2026-10-23** (RTX 3060 12 GB, Heretic awake at 4.8 GB, a game holding 0.5 GB):

| Job | Time | ComfyUI peak VRAM |
|---|---|---|
| Image 1024², 9 steps, models loaded from disk | 68–70 s | 4.7 GB |
| Image 1024², models already loaded | 32 s (3.2 s/step) | 5.0 GB |
| Video 832×480, 81 frames (5 s at 16 fps), 4 steps | 8.1 min | 7.3 GB |

ComfyUI's dynamic VRAM offloads weights to RAM when other processes hold the GPU, so these
ran beside Heretic without stopping it. Heretic fell asleep partway through the video, which
gave ComfyUI more room.

**Sharing the GPU.** Keep Ollama running for Klarheit's trials. Each local call has a 120 s timeout. When a video overlapped the 16:05 trial, the slowest call took 101 s. The hour before, it took 46 s.

`just image` and `just video` wait for an active `klarheit-rv` or `klarheit-m12` run to finish. They also wait if the media job would overlap the next trial (:05 hourly, plus 10:35 and 20:35). Use `--ignore-klarheit` to skip the wait.

Heretic adjusts to the GPU memory it finds. On an idle card it took 9.8 of 12 GB, leaving so little for ComfyUI that `just image` failed with `VRAM grow failed`. Media jobs now run `docker stop
llama-heretic` before starting and `docker start` afterward, even if the job fails or receives SIGTERM, a request to shut down. During that time, `ask_local` returns errors. Use `--keep-heretic` to leave Heretic running. If SIGKILL force-stops the job before cleanup, run `just heretic up -d`.

---

## Speech (whisper.cpp speech-to-text, Chatterbox Nano cloned voices)

Whisper turns recordings into text. Chatterbox reads text aloud and can imitate a voice from a recording. Both run in Docker and accept connections only from this machine. They run on the CPU, leaving GPU memory for Heretic and Ollama. See lineup items #4 and #5 in `docs/proposals/2026-10-22-local-model-lineup.md`.

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

**Speed measured on 2026-10-23.** Other jobs were running on the Ryzen 5 5500 during the tests.

- Whisper transcribed a 30 s clip word for word. It took 31 s at a system load of ~11 and 42 s at ~27. Under heavy load (~40), it took 252 s. That makes it useful for dictation and recordings, where the text can arrive after the speaker finishes. Live captions need to keep up as people speak.
- Chatterbox took about 5 s per sentence. It generated 11.6 s of audio from 3 sentences in 15.4 s. The first use of a voice adds about 3 s. Chatterbox's own voice encoder scored similarity to the reference clip at 0.87 for the clone and 0.56 for the built-in voice. Hear the samples in `/opt/outputs/speech/`.

voice-line runs separately. It uses its own whisper-server and Kokoro on the GPU. See ports 2022 and 8880 in `/opt/proj/.port-registry`.

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

Use Serena when the answer depends on how types fit together across files. For example, you can ask for every caller of an interface method across a repo. An interface defines the methods a type must provide.

Serena uses the Language Server Protocol, or LSP, which lets tools ask a language server questions about code. That helps it follow types across files, including generics, which let code work with different types. It can also work out which implementation a call uses through an interface or trait. It's strongest at these questions in Python, TypeScript, Rust, Go, and C#, and in typed languages generally.

**Invocation.** `uvx --from git+https://github.com/oraios/serena serena start-mcp-server --context ide-assistant`

Serena starts more slowly because it launches real language servers. jCodeMunch queries are cheaper per call.

---

## Context7 (third-party library docs)

Use Context7 whenever a question names a library or framework, such as FastAPI, React, Django, or pandas. It can fetch docs for a specific release, so the answer can use documentation newer than the model's training cutoff. It covers ~30,000+ libraries using llms.txt files, OpenAPI descriptions of web APIs, and websites.

Run `npx -y @upstash/context7-mcp` with Node 18+. An optional free API key lifts rate limits. Get one at https://context7.com/dashboard

---

## DuckDB / MotherDuck MCP (heavy data — SQL over anything)

DuckDB runs SQL, a language for querying data, inside the process that calls it. You can query CSV, Parquet, and JSON files. You can also use S3, GCS, R2, or MotherDuck cloud. There's no separate server to manage.

**Invocation.**
```
# In-memory (default, safe):
uvx mcp-server-motherduck --db-path :memory: --read-write --allow-switch-databases

# Local DuckDB file:
uvx mcp-server-motherduck --db-path /absolute/path/to/db.duckdb

# MotherDuck cloud:
uvx mcp-server-motherduck --db-path md: --motherduck-token $MOTHERDUCK_TOKEN --read-write
```

Reach for DuckDB when you need real SQL, joins across files, Parquet files, remote storage, or a query that jDataMunch's built-in operations can't express.

---

## How they fit together

Start with what you need to find. For a function, look in the code index. For a table, start with the data tools. For an old decision, search session memory. The diagram shows the first tool for each kind of question and where Claude goes next: a fallback, or a tool for heavier or third-party cases.

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

Dreaming looks for mistakes that keep coming up and approaches that have worked before. By default it runs daily at 2 AM. It asks Langfuse for traces, which are records of what an assistant did, since the last run. The `dream-synthesizer` skill reviews those traces and saves the results to memweave and `~/.claude/CLAUDE.md`.

The scheduled job runs `features/dreaming/dream.sh`. Use `/dream` inside Claude Code to run it on demand.

**Install.**
```bash
bash features/dreaming/install.sh
```

Use Dreaming after a project has 10+ Langfuse traces. On the next substantial task, the `prior-art-check` skill runs `mw_search.py` to bring relevant findings into the session. Every session also gets the `## Dreaming
Notes` section from `CLAUDE.md`.

In `state/dreaming.env`, set `DREAMING_CRON_SCHEDULE` for the schedule (default `0 2 * * *`) and `DREAMING_ENABLED` to control whether it runs (default `1`).

---

## Orchestrator + Multi-agent (--decompose mode)

Use `ralph-harness.sh --decompose` to split a product requirements document into tasks. The orchestrator writes the task list as JSON. Bash starts a separate `claude -p` process for each task and runs tasks in parallel where safe. A final agent combines the results. Langfuse groups the recorded activity by `role:`.

| Role | Designated tools |
|---|---|
| `code` | jCodeMunch, Serena |
| `data` | jDataMunch, DuckDB |
| `docs` | jDocMunch, Context7 |
| `memory` | memweave |
| `general` | all tools |

ralph-harness.sh sets AGENT_ROLE for each worker process. Langfuse uses the `role:<value>` tags to show which activity belongs to each worker.

**Usage.**
```bash
./ralph-harness.sh --prd ./PRD.md --decompose --rubric ./.claude/outcomes/rubric.md
```

With both `--decompose` and `--rubric`, the Outcomes grader reviews the combined result after each round. The grader starts with a fresh context and checks the result against the rubric. The loop ends when both the synthesis and the rubric check pass.

Every worker inherits `MCP_TIMEOUT=60000`. The global jCodeMunch PreToolUse and PostToolUse hooks run for each worker. The rules that block destructive Bash commands still apply to every subprocess under `--decompose`.

---

## Session Stats (weekly efficiency reporter)

Session Stats shows how much each project used Claude's tools. By default it runs every Sunday at 8 AM and pulls the past 7 days of traces from Langfuse. It groups them by date and project. The Markdown table shows trace counts, tool calls, and token use. A `⚠ high` flag marks sessions above 40k tokens.

The scheduled job runs `features/session-stats/stats.sh`. Use `/stats` inside Claude Code to run it on demand.

**Output (--cron mode).**

- `~/.claude/dreaming-output/stats-YYYY-MM-DD.md` goes into the next dreaming run, so weekly stats appear in memweave playbooks.
- `state/stats-weekly.md` is for readers. A dashboard can point to it with a symlink, a file that points to another file.

**Install.**
```bash
bash features/session-stats/install.sh
```

**Manual trigger.**
```bash
bash features/session-stats/stats.sh [--days N]
```

Set `STATS_CRON_SCHEDULE` (default `0 8 * * 0`) and `DREAMING_OUTPUT_DIR` (default `~/.claude/dreaming-output`) in `state/session-stats.env`. install.sh writes this file.

---

**SubagentStart hook audit (2026-05-14).** When Claude Code starts a worker, the hook in `~/.claude/settings.json` runs `jcodemunch-mcp hook-subagent-start`. It gives the worker a short guide to the repo. The jcodemunch `--help` text describes it as "SubagentStart hook: inject condensed repo orientation".

The worker gets its tool instructions from the `task` field in the orchestrator's task list. That prompt is the only way to limit which tools a worker uses. The hook only adds orientation. It can't turn off MCP servers, because Claude Code has no per-session switch for that.

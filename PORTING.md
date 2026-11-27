# Hermes Migration Handoff

*You are Claude running inside Hermes. This guide is your complete brief.
Read it from start to finish before changing anything. Then work through
the sections in order and commit as you go.
Ask the user only if a decision would significantly change the cost,
the work involved, or where the data is stored.*

---

## What this is

This guide moves the Refinery's tools and working rules from Claude Code
to Hermes. It leaves behind everything that works only on Windows or
only in Claude Code. Claude Code runs only Claude. Hermes supports other models, can
send updates to a messaging app, and can run while you're away. It can
also turn lessons from a session into skills, which are instructions it
can reuse later.

Use only Debian 13 or Ubuntu 24.04. Skip any step that requires macOS or
Windows and make a note of it.

---

## What we're keeping and what we're dropping

### Keeping — port these

MCP stands for Model Context Protocol. It gives an assistant a standard
way to call an external tool. An MCP server makes that tool available.
For example, jCodeMunch can return the function the assistant asked for,
so the assistant can read it without opening the whole file. SOUL.md is
the file Hermes reads for standing instructions on every turn.

| Component | What it does | Port strategy |
|---|---|---|
| jCodeMunch MCP | Uses Tree-sitter, a tool that reads the structure of code, and index named parts, such as functions. Cuts tokens (chunks of text the model reads) by ~95% when reading code | Connect as an MCP server |
| jDataMunch MCP | Finds rows in files with comma- or tab-separated values (CSV/TSV) | Connect as an MCP server |
| jDocMunch MCP | Finds a specific section in the project docs | Connect as an MCP server |
| memweave | A command-line tool and a store of Markdown notes, with no MCP server. Searches the notes offline by meaning and by keyword (BM25) | Copy the notes and `.venv-memweave`. Run `mw_search.py` from the command line (CLI) |
| Serena MCP | Uses the Language Server Protocol (LSP) to answer questions about code, such as what type a variable has (Python/TS/Rust/Go/C#) | Connect as an MCP server |
| Context7 MCP | Finds docs for a specific version of a third-party library | Connect as an MCP server |
| DuckDB MCP | Runs SQL on Parquet (a file format that stores table data by column), JSON, CSV, and data in S3 (Amazon's object storage service) | Connect as an MCP server |
| Retrieval routing policy | Rules that tell the assistant which tool to use for each kind of request | Paste into SOUL.md |
| jOutputMunch rules | Cuts tokens in replies (-25–40%) | Paste into SOUL.md |
| prior-art-check skill | Requires the assistant to search memweave for past work before starting a substantial task | Port to Hermes skill |
| judge skill | Asks a separate assistant to review code before Edit/Write | Port to Hermes skill |
| Superpowers skills | Brainstorming, TDD (test-driven development, where you write a test before writing the code to pass it), debugging, verification, and more | Port each to Hermes skill |
| Langfuse observability | Records what happened in each turn, including token counts and tool calls | Write Hermes plugin |
| Guardrails — secret scanner | Block secrets in user prompts | Write Hermes tool/hook |
| Guardrails — injection defender | Blocks tool results that try to give the assistant new instructions (prompt injection) | Write Hermes tool/hook |
| Bash-matcher blocklist | Block `rm -rf`, pipe-to-shell, push to main | Configure Hermes tool approval |
| Ralph autonomous loop | Works through a product requirements document (PRD) unattended and checks each result | Schedule it with cron, Hermes' job scheduler |

### Dropping — do not port

- All `.ps1` PowerShell scripts (Windows-only)
- `prerequisites.ps1`, `install.ps1`, `verify.ps1`, `finish-install.ps1`
- `ralph-harness.ps1`
- `healthcheck.ps1`
- Claude Code `settings.json` env block writes
- Claude Code MCP registration commands (`claude mcp add …`)
- Claude Code hook registration (PreToolUse/PostToolUse in settings.json)
- `mcp-clients/*.json.tmpl` (Claude Code client configs)
- `patch-jcodemunch-hook-paths.py` (Claude Code path patching)
- The `install-reliability.ps1` guardrails clone step

---

## Section 1 — Prerequisites (Debian 13)

Use your regular account. Commands that need administrator rights already start with `sudo`.

```bash
# System packages
sudo apt-get update
sudo apt-get install -y \
  python3.11 python3.11-venv python3-pip \
  git curl wget build-essential \
  nodejs npm \
  docker.io docker-compose-plugin \
  jq

# uv — fast Python package manager (Hermes uses it internally)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc   # or open a new shell

# Node 20+ (Context7 needs it)
# If apt gave you an older Node, install via nvm:
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc
nvm install 20
nvm use 20
nvm alias default 20

# Docker group (log out and back in after this)
sudo usermod -aG docker $USER
```

Verify:
```bash
python3.11 --version   # 3.11+
uv --version
node --version         # 20+
docker info            # no permission errors
```

---

## Section 2 — Install Hermes

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
source ~/.bashrc
hermes --version
```

Run the setup wizard:
```bash
hermes setup
```

When it asks for a provider, choose **anthropic** and enter your
`ANTHROPIC_API_KEY`. You can add other providers later. The wizard
creates `~/.hermes/.env` and `~/.hermes/cli-config.yaml`.

Check that Hermes can answer a simple prompt.
```bash
hermes -p "say hello"
```

---

## Section 3 — cli-config.yaml

Edit `~/.hermes/cli-config.yaml`. Use these settings to replace the file or merge them into your existing configuration.

```yaml
model:
  default: "claude-sonnet-4-6"
  provider: "anthropic"

terminal:
  backend: "local"
  cwd: "."
  timeout: 180
  lifetime_seconds: 300

# MCP servers are configured in Section 4.
# Skills live in ~/.hermes/skills/ — Section 6.
```

If you want to use OpenRouter for model switching without changing
provider keys, set `provider: "openrouter"` and add `OPENROUTER_API_KEY`
to `~/.hermes/.env`. Claude is available on OpenRouter as
`anthropic/claude-sonnet-4-6`.

---

## Section 4 — Wire the MCP Retrieval Stack

The Refinery already has the j\*Munch servers installed in
`/opt/proj/Uncle-J-s-Refinery/.venv`. A venv is a Python environment that
keeps a project's packages separate. Hermes can connect to the servers
directly through MCP.

### 4.1 Find the venv binary paths

```bash
VENV=/opt/proj/Uncle-J-s-Refinery/.venv
ls $VENV/bin/ | grep -E "jcode|jdata|jdoc|serena|mcp"
```

Write down the executable names you see. Here are the usual names.
- `jcodemunch-mcp`
- `jdatamunch-mcp`
- `jdocmunch-mcp`

memweave is a command-line tool and a store. It has no MCP server and
isn't installed in the shared venv above. It uses its own environment,
`.venv-memweave` (Python 3.12). See the memweave instructions in Section 4.3.

### 4.2 Discover Hermes MCP config format

```bash
hermes mcp --help
```

Hermes stores MCP servers in `~/.hermes/mcp-servers.json` or accepts
them via `hermes mcp add`. Use whichever the help output shows.

### 4.3 Register each server

Replace `$VENV` with the absolute path to the Refinery venv.

**jCodeMunch:**
```bash
hermes mcp add jcodemunch \
  --command "$VENV/bin/jcodemunch-mcp" \
  --args "serve"
# OR if Hermes uses a JSON config:
```

```json
{
  "jcodemunch": {
    "command": "/opt/proj/Uncle-J-s-Refinery/.venv/bin/jcodemunch-mcp",
    "args": ["serve"],
    "env": {}
  }
}
```

**jDataMunch:**
```bash
hermes mcp add jdatamunch \
  --command "$VENV/bin/jdatamunch-mcp"
```

**jDocMunch:**
```bash
hermes mcp add jdocmunch \
  --command "$VENV/bin/jdocmunch-mcp"
```

**memweave (NOT an MCP server — a CLI + store):**
Copy the Python environment, the scripts, and the notes. Then run the
search command directly or call it from a Hermes skill. The
`hermes mcp add` command only applies to MCP servers.
```bash
# 1. The Python 3.12 venv (memweave requires >=3.12; can't share the 3.11 stack venv)
cp -r /opt/proj/Uncle-J-s-Refinery/.venv-memweave ~/.hermes/.venv-memweave
# 2. The search CLI + sync seam
cp -r /opt/proj/Uncle-J-s-Refinery/scripts/memweave ~/.hermes/scripts/memweave
# 3. The markdown corpus (the source of truth — the sqlite index rebuilds from it)
cp -r ~/.uncle-j-memory ~/.hermes/uncle-j-memory
```
Run a search from the command line.
```bash
~/.hermes/.venv-memweave/bin/python ~/.hermes/scripts/memweave/mw_search.py "<query>" --k 5
```
The Markdown notes are the source of truth. If you delete the SQLite
search index, `sync_memory.sh` rebuilds it byte for byte. Point the Hermes
prior-art skill at the search command.

**Serena (LSP-backed code intelligence):**
Use `uvx` to run Serena outside the Refinery's Python environment.
```bash
hermes mcp add serena \
  --command "uvx" \
  --args "--from" "git+https://github.com/oraios/serena" "serena-mcp-server"
```

**Context7 (third-party library docs):**
Context7 is a Node package.
```bash
hermes mcp add context7 \
  --command "npx" \
  --args "-y" "@upstash/context7-mcp"
```

**DuckDB MCP:**
```bash
hermes mcp add duckdb \
  --command "uvx" \
  --args "mcp-server-motherduck" "--db-path" ":memory:" "--read-only" "false"
```

### 4.4 Verify all servers connect

```bash
hermes mcp list
# All 7 should show as connected.
```

If a server fails to connect, run `hermes doctor` and read the error.

- If Hermes can't find the executable, give it the full path.
- If a setting is missing from the environment, add it to `~/.hermes/.env`.
- If uvx takes too long to start, increase `hermes mcp timeout` if that option is available.

---

## Section 5 — SOUL.md (Routing Policy + Output Rules)

Hermes reads `~/.hermes/SOUL.md` as a set of standing instructions on
every turn. Put the Refinery's tool-routing rules and its jOutputMunch
reply rules from CLAUDE.md here.

Create or replace `~/.hermes/SOUL.md`:

```markdown
# Retrieval Stack Routing Policy

You have a dedicated retrieval stack. Always consult it before falling
back to brute-force file reading, grep, or shell commands.

## Tools by modality — first choice wins

| Request shape | Primary tool | Fallback |
|---|---|---|
| Source code: find / read / analyze a symbol | **jcodemunch** | serena, then read file |
| Source code: cross-file refs, types, generics | **serena** (real LSP) | jcodemunch |
| CSV / TSV / small tabular file | **jdatamunch** | duckdb |
| Parquet / S3 / complex SQL / joins across files | **duckdb** | jdatamunch |
| My own project docs / runbooks / markdown | **jdocmunch** | read file |
| Third-party library documentation | **context7** | web search |
| "What did we decide / discuss / build before?" | **memweave** (`mw_search.py`) | session transcript |
| General web / news / current events | web search | — |

## Operating rules

**Code work — jCodeMunch first, Serena for LSP-hard questions**
- Use `search_symbols`, `get_file_outline`, `get_repo_outline` for
  orientation. Never read a source file just to "see what's in it."
- Before editing a function, call `get_symbol_source` for that function.
- Before committing to a change, call `get_blast_radius`.
- For type resolution or "find all callers across files," prefer serena.
- Use `plan_turn` as opening move on an unfamiliar repo.
- Use `winnow_symbols` when filtering by kind + complexity + churn.

**Data work — jDataMunch for CSVs, DuckDB for real SQL**
- For CSV/TSV: `describe_dataset` first, `get_rows` with filters next.
- For Parquet, JSON, remote data, or joins: use duckdb directly.

**Docs work — jDocMunch (mine), Context7 (theirs)**
- For project docs: ask jdocmunch for sections by heading, not whole files.
- For third-party library questions: context7 is authoritative.

**Memory — memweave before web search or re-asking**
- Start every non-trivial task with a memweave search (`mw_search.py "<query>" --k 5`).
- "Have we solved this before?" is always question #1.
- No manual snapshot needed — the Stop-hook + nightly `sync_memory.sh` ingest the session
  into the memweave corpus automatically.

**Verification before landing changes**
- Before finalizing code changes: `get_changed_symbols`, `get_untested_symbols`,
  `get_pr_risk_profile`. Report the risk score.

**Format economy**
- Pass `format="auto"` on jCodeMunch calls that might return large responses.

## When to fall back to direct file access

Only when:
- The file type is binary, image, or not understood by any retrieval tool.
- An indexing step has failed and you've told the user.
- The user explicitly asks for native file access.

Say so before switching tools.

---

# Output Efficiency Rules

Apply these to every response. No exceptions.

## Prose
- Lead with the answer. No preamble, no restating the question.
- Use contractions.
- No filler vocabulary: delve, tapestry, leverage, multifaceted, seamless,
  groundbreaking, utilize, harness, foster, bolster, elevate, reimagine,
  revolutionize, spearhead, navigate, illuminate, transcend, resonate,
  showcase, entwine, amplify, augment, maximize, champion, uncover, unveil.
- No closers: "I hope this helps", "Let me know if you need anything else".
- No openers: "Great question!", "That's interesting!", "Absolutely!".
- One qualifier per claim. No hedge-stacking.
- Short sentences. Three commas → split the sentence.
- Do not restate what was just established.

## Code work
- Do not narrate what you are about to do. Do it.
- Do not summarize what you just did. The diff is visible.
- Show only the changed lines, not unchanged surrounding context.
- Explain code only when the logic is non-obvious.
- Do not explain language fundamentals.
- "It's in handlers.py:42" — not a narrated search journey.

## Structured output
- Compact JSON: no indentation, compact separators.
- Never repeat back parameters the caller provided.
- Omit null, empty array, empty object keys.
- No `success: true` on success — absence of error implies success.

## Errors
- Structured error data, not apologetic prose.
  `{"error":"not_found","path":"/x/y"}` — not a paragraph of apology.
```

---

## Section 6 — Port the Skills

Save each skill as a Markdown file named `<skill-name>.md` in
`~/.hermes/skills/`. To use it, type `/<skill-name>` in a conversation.

### 6.1 Create the skills directory

```bash
mkdir -p ~/.hermes/skills
```

### 6.2 prior-art-check

Write `~/.hermes/skills/prior-art-check.md`:

```markdown
# Prior-art check

Every time a new conversation starts on a non-trivial task, query
memweave before the first substantive tool call. "Have we already
solved this?" — asked before the work.

## When to trigger

Run when ANY of these are true:
- request is about code, architecture, debugging, or design
- user asks "how", "why", "what about", "should I", "what's the best"
- request references a specific project, file, or component
- you're about to call a retrieval tool on anything non-trivial

Do NOT trigger for small talk or obviously current-events questions.

## Steps

1. Pull 2–4 keywords from the request. Keep it short and concrete.
2. Run `mw_search.py "<those keywords>" --k 5` (the memweave search CLI).
3. Interpret:
   - High relevance hits: summarize top 1–2, tell the user "we've
     touched this before: …", then continue with that context.
   - Low relevance: note briefly, then proceed.
   - No hits: say "no prior work found" and proceed.
4. Continue the task using the retrieval routing policy.

## What NOT to do
- Don't let a miss block progress. It's context, not a gate.
- Don't surface raw memory IDs. Translate to user-friendly summaries.
- Don't call it repeatedly in the same session for the same topic.
```

### 6.3 judge

Write `~/.hermes/skills/judge.md`:

```markdown
# Judge — verify before commit

Spawn an independent second opinion before landing any non-trivial
code change.

## When to trigger

Run BEFORE the final write on any of these:
- function signature change
- refactor touching more than one file
- new public API, schema, or route
- user flags the change as "important" or "risky"
- explicit "verify", "double-check", "review before commit" requests

Skip for: typos, formatting, single-character edits, tests for
existing behavior, changes already reviewed this turn.

## Steps

**Step 1 — gather structural evidence**

Call these on the symbols you're about to touch:
- `get_changed_symbols` — map planned diff to exact symbols
- `get_blast_radius` — depth-weighted impact
- `find_references` or `find_referencing_symbols` — who else calls this
- `get_untested_symbols` — flags changes with no test coverage
- `get_pr_risk_profile` — composite score 0.0–1.0

**Step 2 — spawn an independent reviewer**

Spawn a subagent. The prompt MUST be self-contained.

Template:
```
Independent review of a proposed change.

WHAT CHANGED:
<paste the proposed diff>

STRUCTURAL EVIDENCE:
- Symbols touched: <get_changed_symbols output>
- Blast radius (depth=2): <get_blast_radius output>
- Callers: <find_references output>
- Untested among touched: <get_untested_symbols output>
- PR risk score: <score>/1.0 — <top recommendations>

STATED INTENT:
<one-paragraph summary of what the change accomplishes>

REVIEW CHECKLIST:
1. Does the diff actually accomplish the stated intent?
2. Are any callers broken? Flag specific file:line.
3. Are any type/signature invariants violated?
4. Are there hallucinated functions or imports not in the codebase?
5. Is the risk profile acceptable for the stated intent?
6. What's the ONE thing that could still go wrong? (Required.)

Report in <200 words.
VERDICT: approve | approve-with-concerns | block
CONCERNS: <bulleted; empty if approve>
ONE THING THAT COULD STILL GO WRONG: <always answer>
```

**Step 3 — act on the verdict**

- `approve` — proceed.
- `approve-with-concerns` — show concerns to user, ask whether to proceed.
- `block` — do NOT land the change. Report the blocker, propose a fix,
  re-run judge on the revised change.

**Step 4 — log to the memweave corpus if non-approve**

Append a short note to the memory corpus: what was tried, what blocked it.
```

### 6.4 brainstorm

Write `~/.hermes/skills/brainstorm.md`:

```markdown
# Brainstorm — explore before building

Use this before any creative work: new features, building components,
adding functionality, or modifying behavior.

## Purpose

Surface requirements, constraints, and design tradeoffs BEFORE writing
code. One conversation-turn of brainstorming eliminates a day of
backtracking.

## Steps

1. **Restate the goal** in your own words. Confirm you and the user
   are aligned on what "done" looks like.
2. **Ask exactly 3 clarifying questions** — no more. Choose the three
   that most change the implementation path.
3. **After user answers**, propose 2–3 concrete approaches:
   - For each: name it, describe it in 2 sentences, name the main tradeoff.
4. **Recommend one** and say why. The user can redirect.
5. **Only start implementation after the user agrees** on the approach.

## What NOT to do
- Do not implement anything during brainstorming.
- Do not ask more than 3 questions.
- Do not present approaches without tradeoffs — "pros and cons" is not
  a tradeoff, a real tradeoff is "faster but brittle under load".
```

### 6.5 systematic-debugging

Write `~/.hermes/skills/systematic-debugging.md`:

```markdown
# Systematic debugging

Use when encountering any bug, test failure, or unexpected behavior,
before proposing fixes.

## Steps

1. **Reproduce first.** State exactly how to reproduce the bug. If you
   can't reproduce it, say so — do not guess at a fix.

2. **Hypothesize.** List 2–3 concrete hypotheses about root cause.
   Each must be falsifiable (testable with an observation or command).

3. **Test the cheapest hypothesis first.** Run a targeted command,
   read a specific symbol, check a specific log line. Do NOT read
   whole files on a hunch.

4. **Eliminate.** If the hypothesis is wrong, cross it off and state
   what you learned. Move to the next.

5. **Fix only the confirmed root cause.** Not the symptoms. Not the
   adjacent ugly code. The root cause.

6. **Verify the fix.** Run the reproduction case. Confirm the bug is
   gone. Confirm nothing adjacent broke.

7. **Log to the memweave corpus.** One sentence: what the bug was and what fixed it.

## What NOT to do
- Do not propose a fix before reproducing the bug.
- Do not "try a few things and see". Each action must test a hypothesis.
- Do not fix adjacent issues in the same change — separate PR.
```

### 6.6 tdd (test-driven development)

Write `~/.hermes/skills/tdd.md`:

```markdown
# TDD — test-driven development

Use when implementing any feature or bugfix.

## The cycle

1. **Write a failing test** that describes the desired behavior.
   Run it — confirm it fails for the right reason.
2. **Write the minimum code** to make the test pass.
   Do not add anything the test doesn't require.
3. **Refactor** only after the test passes. Keep tests green throughout.
4. **Repeat** for the next behavior unit.

## Rules

- Tests go in before implementation. No exceptions.
- If writing the test is hard, the interface is wrong. Fix the interface.
- A test that never fails is not a test.
- Mock only at system boundaries (external APIs, filesystem, clocks).
  Do not mock internal code.

## What counts as a test

- Unit test for pure logic
- Integration test for anything touching a database, API, or filesystem
- Regression test for any bug that ships

A function with no test is a liability. Flag it with `get_untested_symbols`
and add a test before editing.
```

### 6.7 verification-before-completion

Write `~/.hermes/skills/verify.md`:

```markdown
# Verification before completion

Use before claiming work is complete, fixed, or passing. Evidence
before assertions, always.

## Steps

1. Run the actual verification command. Do not skip it.
2. Paste or summarize the output. Do not say "should work".
3. If verification fails, fix and re-verify. Do not claim success
   on a partial result.

## For code changes

Before claiming a code change is done:
- `get_changed_symbols` — confirm the symbols you intended to touch
- `get_untested_symbols` — flag any newly untested symbols
- `get_pr_risk_profile` — report the risk score to the user
- Run the test suite. Paste the pass/fail count.

## Forbidden phrases without evidence

- "This should work"
- "The fix is in place"
- "Tests are passing"
- "All done"

None of these is a claim you can make without running something.
```

### 6.8 writing-plans

Write `~/.hermes/skills/write-plan.md`:

```markdown
# Write a plan before complex implementation

Use when you have requirements for a multi-step task, before touching code.

## Steps

1. **Decompose** the task into discrete steps. Each step must have:
   - A clear, testable done-state
   - An estimated complexity (small / medium / large)
   - Dependencies on prior steps (if any)

2. **Identify the critical path** — the sequence of steps that determines
   total time if done serially.

3. **Flag risks** — steps where you're uncertain, where the scope could
   expand, or where a wrong choice would require backtracking.

4. **Present the plan to the user** and get explicit agreement before
   starting any implementation step.

5. **Execute one step at a time.** Mark each done as you go. Do not
   jump ahead.

## Format

```
## Plan: <task name>

### Steps
1. [ ] <step> — <done-state> — <complexity>
2. [ ] <step> — <done-state> — <complexity>
   depends on: step 1
...

### Critical path: steps 1 → 3 → 5

### Risks
- Step 3: <why uncertain>
```
```

---

## Section 7 — Langfuse Observability

Use Langfuse to see what happened in a turn. A trace records the tools
Hermes called and how many tokens it used. You can search these records
later. Hermes doesn't record this information by default, so add a
Python wrapper to pass events from Hermes to a local Langfuse instance.

### 7.1 Spin up Langfuse (self-hosted Docker)

The Refinery's existing Langfuse stack is reusable. If it's not running:

```bash
cd /opt/proj/Uncle-J-s-Refinery/claude-code-langfuse-template
docker compose up -d
```

Check the status and wait for every container to report that it's healthy.
```bash
docker compose ps
```

Open Langfuse at http://localhost:3050 and go to Settings → API Keys to get your keys.
```
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_HOST=http://localhost:3050
```

Add them to `~/.hermes/.env`.

### 7.2 Install the Langfuse SDK

```bash
uv pip install --python /opt/proj/Uncle-J-s-Refinery/.venv/bin/python langfuse
# OR install into a new venv Hermes can use:
pip install langfuse
```

### 7.3 Write the Langfuse plugin

Check whether Hermes has a plugin directory:
```bash
ls ~/.hermes/plugins/ 2>/dev/null || mkdir -p ~/.hermes/plugins
hermes plugins --help
```

Write `~/.hermes/plugins/langfuse_tracer.py`:

```python
"""
Hermes plugin: emit one Langfuse trace per conversation turn.

Drop this file in ~/.hermes/plugins/ and Hermes will load it
automatically (verify with `hermes plugins list`).

If Hermes doesn't auto-discover plugins from this path, register
it manually: hermes plugins install langfuse_tracer.py
"""

import os
import time
from langfuse import Langfuse

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = Langfuse(
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            host=os.environ.get("LANGFUSE_HOST", "http://localhost:3050"),
        )
    return _client


def on_turn_start(context: dict) -> None:
    """Called when a new user turn begins."""
    context["_lf_trace"] = _get_client().trace(
        name="hermes-turn",
        user_id=context.get("user_id", "local"),
        session_id=context.get("session_id"),
        input=context.get("user_message"),
        metadata={"model": context.get("model")},
    )
    context["_lf_start"] = time.time()


def on_tool_call(context: dict, tool_name: str, tool_input: dict) -> None:
    """Called before each tool invocation."""
    trace = context.get("_lf_trace")
    if trace:
        context["_lf_span"] = trace.span(
            name=f"tool:{tool_name}",
            input=tool_input,
        )


def on_tool_result(context: dict, tool_name: str, result: dict) -> None:
    """Called after each tool invocation."""
    span = context.get("_lf_span")
    if span:
        span.end(output=result)


def on_turn_end(context: dict, response: str, usage: dict) -> None:
    """Called when the assistant finishes responding."""
    trace = context.get("_lf_trace")
    if trace:
        elapsed = time.time() - context.get("_lf_start", time.time())
        trace.update(
            output=response,
            metadata={
                "elapsed_seconds": round(elapsed, 2),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            },
        )
        _get_client().flush()
```

> **Note:** Hermes' plugin hook signatures may differ from the above.
> After installing, run `hermes plugins list` to confirm it loaded.
> Check `hermes plugins hooks` or the Hermes docs for the exact hook
> names. Adapt the function signatures if needed. The Langfuse SDK calls
> (`trace`, `span`, `flush`) are stable.

### 7.4 Verify tracing

```bash
hermes -p "test turn"
curl -s "http://localhost:3050/api/public/traces?limit=1" \
  -H "Authorization: Basic $(echo -n "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" | base64)" \
  | python3 -m json.tool | head -20
```

You should see a trace with the test message.

---

## Section 8 — Security and Governance

### 8.1 What Hermes already has

Check these before writing anything new:
```bash
# These tools ship with Hermes:
# tools/path_security.py   — blocks path traversal
# tools/url_safety.py      — blocks dangerous URLs
# tools/tirith_security.py — policy enforcement
# tools/skills_guard.py    — protects skill definitions
```

Run `hermes tools` to see which security tools are enabled.

### 8.2 Secret scanner (UserPromptSubmit equivalent)

The Refinery checked each user message for secrets such as API keys.
In Hermes, run the same check before the message reaches the model.
Use a pre-turn hook (code that runs before a turn starts) or a tool guard.

Write `~/.hermes/plugins/secret_scanner.py`:

```python
"""
Block user messages that appear to contain secrets before they're
sent to the model.
"""

import re

_SECRET_PATTERNS = [
    r"sk-[a-zA-Z0-9]{20,}",           # OpenAI-style keys
    r"sk-lf-[a-f0-9]{16,}",           # Langfuse secret keys
    r"AKIA[0-9A-Z]{16}",               # AWS access key IDs
    r"ghp_[a-zA-Z0-9]{36}",           # GitHub personal access tokens
    r"(?i)password\s*[:=]\s*\S{8,}",  # inline password assignments
    r"(?i)api[_-]?key\s*[:=]\s*\S{8,}", # inline API key assignments
    r"-----BEGIN\s+(RSA |EC |OPENSSH )?PRIVATE KEY-----", # PEM keys
]

_COMPILED = [re.compile(p) for p in _SECRET_PATTERNS]


def on_user_message(context: dict, message: str) -> str | None:
    """
    Return None to pass through, or return an error string to block.
    Hermes will show the error string to the user instead of sending
    the message to the model.
    """
    for pattern in _COMPILED:
        if pattern.search(message):
            return (
                "Message blocked: it appears to contain a secret or credential. "
                "Remove the secret and try again. Never paste keys, passwords, "
                "or tokens directly into a conversation."
            )
    return None
```

### 8.3 Bash-matcher blocklist (destructive command guard)

Use Hermes' tool approval settings to require confirmation before
dangerous commands run.
```bash
hermes tools config --help
hermes config set tool_approval strict
```

Check `hermes tools --help` for the exact syntax. Add these patterns to
the list of commands Hermes should block.

```
rm -rf /
rm -rf ~
rm -rf $HOME
curl * | bash
curl * | sh
wget * | bash
wget * | sh
git push --force
git push -f
git push origin main
git push origin master
chmod 777 /
sudo rm
```

### 8.4 Prompt injection defender (PostToolUse equivalent)

A tool result can contain text that tells the assistant to ignore its
instructions. This check looks for that kind of text before Hermes
passes the result to the model.

Write `~/.hermes/plugins/injection_defender.py`.

```python
"""
Scan tool results for prompt injection patterns before they're
appended to the context.
"""

import re

_INJECTION_PATTERNS = [
    r"ignore (all )?previous instructions",
    r"disregard (all )?previous",
    r"new instructions?:",
    r"system prompt:",
    r"you are now",
    r"forget everything",
    r"<\|.*?\|>",             # special token injection attempts
    r"\[INST\]",              # Llama instruction injection
    r"###\s*instruction",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


def on_tool_result(context: dict, tool_name: str, result: str) -> str:
    """
    Called after each tool returns. Return a modified result string
    to sanitize, or the original result to pass through.
    """
    for pattern in _COMPILED:
        if pattern.search(result):
            return (
                f"[INJECTION ATTEMPT BLOCKED in result from '{tool_name}'] "
                "The tool result contained patterns consistent with prompt "
                "injection and was sanitized. Raw result not shown."
            )
    return result
```

---

## Section 9 — Ralph Equivalent (Autonomous Loop)

Ralph works through a product requirements document (PRD) one item at a
time. It checks the result, commits the change, and repeats. In Hermes,
cron runs the work on a schedule and the soul file supplies standing
instructions.

### 9.1 One-shot Ralph invocation

For an unattended work session on a specific project:

```bash
hermes -p "$(cat /path/to/project/PRD.md)

Read this PRD end-to-end. Execute the highest-priority incomplete item
from the acceptance criteria. Verify the result. Commit to git. Report
what was done and what's next."
```

### 9.2 Recurring Ralph (scheduled)

```bash
hermes cron create "0 */4 * * *" \
  "Read /path/to/project/PRD.md. Find the first incomplete acceptance
   criterion. Execute it. Verify. Commit. Report done/blocked." \
  --name "ralph-loop" \
  --deliver local
```

Change the schedule by editing the cron expression, the text that tells
Hermes when to run. With `local` delivery, Hermes saves the result to a
log file and you don't need a messaging platform.

To deliver results to Telegram (recommended for unattended work):
```bash
hermes cron create "0 */4 * * *" \
  "Read /path/to/project/PRD.md …" \
  --name "ralph-loop" \
  --deliver telegram
```

### 9.3 Verification gate inside Ralph

Give every item in the PRD a testable condition for calling it done.
For example, require a named test to pass before Ralph marks the item
complete. Include this instruction in the cron prompt.

> "Do not mark an item complete until you have run the verification
> command for it and pasted the output. If the command fails, report
> blocked and stop."

---

## Section 10 — memweave Memory Migration

To bring your saved notes into Hermes, copy the Markdown files and
rebuild the SQLite search index from them.

```bash
# The Refinery's memweave corpus
ls ~/.uncle-j-memory/memory/ 2>/dev/null

# Copy to the Hermes location (set in Section 4.3)
cp -r ~/.uncle-j-memory/ ~/.hermes/uncle-j-memory/

# Rebuild the index from the markdown (byte-identical from the corpus)
~/.hermes/.venv-memweave/bin/python ~/.hermes/scripts/memweave/sync_memory.sh
```

Use the search command to check that Hermes can find the notes you copied.
```bash
~/.hermes/.venv-memweave/bin/python ~/.hermes/scripts/memweave/mw_search.py "Uncle J" --k 5
```

The results should include memories saved in the Refinery. If they
don't, the copy didn't work.

---

## Section 11 — Self-Improving Skills

Hermes can turn a solution from a complex task into a skill it can reuse
in later sessions.

Enable it:
```bash
hermes config set auto_skill_creation true
```

After a session where you solved a substantial problem, ask Hermes to draft a skill.
```
/skills new
Name: <skill-name>
Description: <what this skill does>
Trigger: <when to invoke it>
```

Hermes uses the conversation history to draft the skill. Read the draft,
make any edits, and save it.
```bash
hermes skills save <skill-name>
```

The skill is now available as `/<skill-name>` in all future sessions.

---

## Section 12 — Verification Checklist

Run these after completing all sections. Everything must pass.

```bash
# 1. Hermes starts cleanly
hermes -p "hello" && echo "PASS: hermes starts"

# 2. All 6 MCP servers connected (memweave is a separate CLI, not counted here)
hermes mcp list | grep -c "connected"
# Expected: 6

# 3. jCodeMunch responds
hermes -p "use jcodemunch to list repos" && echo "PASS: jcodemunch"

# 4. memweave responds (CLI, not MCP)
~/.hermes/.venv-memweave/bin/python ~/.hermes/scripts/memweave/mw_search.py "Uncle J" --k 5 && echo "PASS: memweave"

# 5. Skills load
hermes -p "/prior-art-check" && echo "PASS: prior-art-check skill"
hermes -p "/judge" && echo "PASS: judge skill"

# 6. Langfuse receives traces
hermes -p "trace test"
sleep 3
curl -s "http://localhost:3050/api/public/traces?limit=1" \
  -H "Authorization: Basic $(echo -n "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" | base64)" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('PASS: langfuse' if d.get('data') else 'FAIL: no trace')"

# 7. Secret scanner fires
hermes -p "my key is sk-abc123abc123abc123abc123" 2>&1 | grep -q "blocked" && echo "PASS: secret scanner"

# 8. SOUL.md loaded (routing policy present)
hermes -p "what retrieval tool do you use for CSV files?" | grep -qi "jdatamunch" && echo "PASS: soul routing"
```

---

## Section 13 — First Conversation After Migration

Once everything passes, open Hermes and paste this to complete the
migration:

```
/prior-art-check hermes migration uncle j's refinery

I've just migrated from Uncle J's Refinery to Hermes. The following
is now configured:
- 6 MCP retrieval servers (jCodeMunch, jDataMunch, jDocMunch,
  Serena, Context7, DuckDB) + memweave memory as a separate CLI
- Retrieval routing policy and jOutputMunch rules in SOUL.md
- Skills: prior-art-check, judge, brainstorm, systematic-debugging,
  tdd, verify, write-plan
- Langfuse tracing to http://localhost:3050
- Secret scanner and injection defender plugins
- Ralph equivalent via hermes cron

This session is auto-ingested into the memweave corpus, so future sessions start with context.
For a durable standalone note, append this summary to `~/.hermes/uncle-j-memory/memory/`.
```

---

## What you should NOT port

Skip these Windows and Claude Code components when you move to Hermes.

- Any `.ps1` file
- `install.ps1`, `prerequisites.ps1`, `verify.ps1`, `finish-install.ps1`
- `ralph-harness.ps1`
- `healthcheck.ps1`
- `patch-jcodemunch-hook-paths.py` (Claude Code path patching)
- `mcp-clients/*.json.tmpl` (Claude Code client configs)
- Claude Code `settings.json` writing logic
- `claude mcp add` commands
- Claude Code hook registration (PreToolUse/PostToolUse/PreCompact hooks
  in `.claude/settings.json`)
- `install-reliability.ps1` clone step
- Windows-specific docker desktop instructions

---

## Author's note

The Refinery gave Claude Code tools to find a function or a section
of a document, keep its replies short, and record what it did. Hermes
adds scheduled runs, phone updates, and a choice of models. Together
they work better than either does alone.

With the j*Munch servers connected, Hermes can look up code, data, and
docs. It can run on a $5 virtual private server (VPS), send a report to
Telegram, and save a lesson from the work as a skill. The memweave
corpus keeps past sessions and decisions so nothing gets lost. Search
it when you pick up a project again.

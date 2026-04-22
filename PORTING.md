# Hermes Migration Handoff

*You are Claude running inside Hermes. This document is your complete
brief. Read it end-to-end before touching anything, then execute each
section in order. Commit as you go. Ask the user only when a decision
materially changes cost, scope, or data residency.*

---

## What this is

Uncle J's Refinery was an enhancement layer bolted onto Claude Code. It
worked. But Claude Code is Claude-only, has no messaging gateway, no
self-improving skills, and no way to run unattended. Hermes fixes all of
that. This migration carries every valuable idea from the Refinery into
Hermes — and leaves everything Windows and Claude-Code-specific behind.

**Platform:** Debian 13 / Ubuntu 24.04. Nothing else. If a step only
works on macOS or Windows, skip it and note it.

---

## What we're keeping and what we're dropping

### Keeping — port these

| Component | What it does | Port strategy |
|---|---|---|
| jCodeMunch MCP | Tree-sitter symbol index; ~95% token reduction on code reading | Wire as MCP server |
| jDataMunch MCP | CSV/TSV structural retrieval | Wire as MCP server |
| jDocMunch MCP | Section-precise project doc retrieval | Wire as MCP server |
| MemPalace MCP | Long-term verbatim memory with semantic search | Wire as MCP server |
| Serena MCP | LSP-backed code intelligence (Python/TS/Rust/Go/C#) | Wire as MCP server |
| Context7 MCP | Third-party library docs, version-pinned | Wire as MCP server |
| DuckDB MCP | SQL over Parquet/JSON/CSV/S3 | Wire as MCP server |
| Retrieval routing policy | Which tool to call for which request shape | Paste into SOUL.md |
| jOutputMunch rules | Output token discipline (-25–40%) | Paste into SOUL.md |
| prior-art-check skill | Force MemPalace lookup before non-trivial work | Port to Hermes skill |
| judge skill | Independent code-reviewer subagent before Edit/Write | Port to Hermes skill |
| Superpowers skills | brainstorm, TDD, debugging, verification, etc. | Port each to Hermes skill |
| Langfuse observability | Per-turn tracing, token counts, tool call logs | Write Hermes plugin |
| Guardrails — secret scanner | Block secrets in user prompts | Write Hermes tool/hook |
| Guardrails — injection defender | Block prompt injection in tool results | Write Hermes tool/hook |
| Bash-matcher blocklist | Block `rm -rf`, pipe-to-shell, push to main | Configure Hermes tool approval |
| Ralph autonomous loop | PRD-driven unattended iteration with verification gates | Port to Hermes cron |

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

Run as your normal user. `sudo` where marked.

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

First smoke test:
```bash
hermes -p "say hello"
```

---

## Section 3 — cli-config.yaml

Edit `~/.hermes/cli-config.yaml`. Replace or merge with:

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

The j\*Munch servers and friends are already installed in the Refinery
venv at `/opt/proj/Uncle-J-s-Refinery/.venv`. Hermes speaks MCP natively.

### 4.1 Find the venv binary paths

```bash
VENV=/opt/proj/Uncle-J-s-Refinery/.venv
ls $VENV/bin/ | grep -E "jcode|jdata|jdoc|mempalace|serena|mcp"
```

Note the actual binary names. Typical output:
- `jcodemunch-mcp`
- `jdatamunch-mcp`
- `jdocmunch-mcp`
- `mempalace`

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

**MemPalace:**
```bash
hermes mcp add mempalace \
  --command "$VENV/bin/mempalace" \
  --args "serve" \
  --env "MEMPALACE_STORE_PATH=$HOME/.hermes/mempalace"
```

MemPalace needs a store path. `~/.hermes/mempalace` is a clean location
that Hermes owns. If you want to migrate existing memories from the
Refinery, copy `~/.mempalace/` (or wherever the Refinery stored them)
to `~/.hermes/mempalace/` before first use.

**Serena (LSP-backed code intelligence):**
Serena runs via `uvx`. It's not in the Refinery venv.
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

If any fail, check `hermes doctor` and examine the error. Common fixes:
- Binary not found: use absolute path
- Missing env var: add to `~/.hermes/.env`
- uvx cold start timeout: increase `hermes mcp timeout` if the option exists

---

## Section 5 — SOUL.md (Routing Policy + Output Rules)

`~/.hermes/SOUL.md` is loaded as the agent's system-level instruction on
every turn. This is where the Refinery's CLAUDE.md routing policy and
jOutputMunch rules live in Hermes.

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
| "What did we decide / discuss / build before?" | **mempalace** | session transcript |
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

**Memory — mempalace before web search or re-asking**
- Start every non-trivial task with a mempalace search.
- "Have we solved this before?" is always question #1.
- Snapshot the session into MemPalace before compaction or end of day.

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

Hermes skills live in `~/.hermes/skills/`. Each skill is a markdown file
named `<skill-name>.md`. Invoke with `/<skill-name>` in a conversation.

### 6.1 Create the skills directory

```bash
mkdir -p ~/.hermes/skills
```

### 6.2 prior-art-check

Write `~/.hermes/skills/prior-art-check.md`:

```markdown
# Prior-art check

Every time a new conversation starts on a non-trivial task, call
MemPalace before the first substantive tool call. "Have we already
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
2. Call mempalace search with those keywords, limit 5.
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

**Step 4 — log to MemPalace if non-approve**

Write a short memory: what was tried, what blocked it.
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

7. **Log to MemPalace.** One sentence: what the bug was and what fixed it.

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

Langfuse gives you per-turn tracing, token counts, tool call logs, and a
searchable audit trail. Hermes doesn't have this built in — we add it via
a Python wrapper script that proxies the Hermes process and ships events
to a local Langfuse instance.

### 7.1 Spin up Langfuse (self-hosted Docker)

The Refinery's existing Langfuse stack is reusable. If it's not running:

```bash
cd /opt/proj/Uncle-J-s-Refinery/claude-code-langfuse-template
docker compose up -d
```

Wait for all containers healthy:
```bash
docker compose ps
```

Langfuse UI: http://localhost:3050

Get your keys from the Langfuse UI (Settings → API Keys):
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

The Refinery's secret scanner fired on every user message. Port it as a
Hermes pre-turn hook or tool guard.

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

Hermes' tool approval system can be configured to require confirmation
for dangerous commands. Check:
```bash
hermes tools config --help
hermes config set tool_approval strict
```

Add explicit blocklist rules via Hermes tool approval config (exact
syntax: check `hermes tools --help`). Patterns to block:

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

Write `~/.hermes/plugins/injection_defender.py`:

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

Ralph was a PRD-driven loop: read the PRD, do a unit of work, verify,
commit, repeat. Hermes does this natively with cron + a soul file.

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

Adjust the cron expression to your cadence. `local` delivery saves
output to a log file without requiring a messaging platform.

To deliver results to Telegram (recommended for unattended work):
```bash
hermes cron create "0 */4 * * *" \
  "Read /path/to/project/PRD.md …" \
  --name "ralph-loop" \
  --deliver telegram
```

### 9.3 Verification gate inside Ralph

The PRD should always include acceptance criteria that Ralph can test.
The pattern from the Refinery works directly — the criteria list is the
verification gate. Tell the agent in the cron prompt:

> "Do not mark an item complete until you have run the verification
> command for it and pasted the output. If the command fails, report
> blocked and stop."

---

## Section 10 — MemPalace Migration

If you have memories in the Refinery's MemPalace that you want in
Hermes:

```bash
# Find where the Refinery stores MemPalace data
ls ~/.mempalace/ 2>/dev/null || find ~ -name "*.mempalace" 2>/dev/null

# Copy to the Hermes MemPalace location (set in Section 4.3)
cp -r ~/.mempalace/ ~/.hermes/mempalace/
```

After copying, verify the MCP server sees the data:
```bash
hermes -p "/prior-art-check Uncle J's Refinery"
```

You should see existing memories surface.

---

## Section 11 — Self-Improving Skills

This is the feature the Refinery never had. After completing a complex
task, Hermes can write a new skill capturing what it learned.

Enable it:
```bash
hermes config set auto_skill_creation true
```

After any session where you solved a non-trivial problem, prompt:
```
/skills new
Name: <skill-name>
Description: <what this skill does>
Trigger: <when to invoke it>
```

Hermes will draft the skill from the conversation history. Review it,
edit if needed, then:
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

# 2. All 7 MCP servers connected
hermes mcp list | grep -c "connected"
# Expected: 7

# 3. jCodeMunch responds
hermes -p "use jcodemunch to list repos" && echo "PASS: jcodemunch"

# 4. MemPalace responds
hermes -p "search mempalace for 'Uncle J'" && echo "PASS: mempalace"

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
- 7 MCP retrieval servers (jCodeMunch, jDataMunch, jDocMunch,
  MemPalace, Serena, Context7, DuckDB)
- Retrieval routing policy and jOutputMunch rules in SOUL.md
- Skills: prior-art-check, judge, brainstorm, systematic-debugging,
  tdd, verify, write-plan
- Langfuse tracing to http://localhost:3050
- Secret scanner and injection defender plugins
- Ralph equivalent via hermes cron

Save this to MemPalace so future sessions start with context.
Wing: hermes_refinery. Room: setup.
```

---

## What you should NOT port

To be explicit: these things from the Refinery have no place in Hermes.
Do not attempt to port them.

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

The Refinery was built to solve a real problem: Claude Code needed
structural retrieval, output discipline, and observability that it
didn't ship with. Hermes solves the other half of the problem — running
unattended, reaching you on your phone, supporting any model.

The combination is legitimately better than either alone. The j*Munch
MCP servers give Hermes structural code/data/doc retrieval that no other
agent has out of the box. Hermes gives those tools a runtime that can
run on a $5 VPS, report to Telegram, and improve itself over time.

Good luck. The whole point of MemPalace is that nothing gets lost.
Use it.

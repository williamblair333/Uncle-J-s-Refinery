# Uncle J's Refinery — Dreaming Integration Handoff

**Date:** 2026-05-12  
**Source article:** "Anthropic introduces 'dreaming,' a system that lets AI agents learn from their own mistakes" — VentureBeat, May 7, 2026  
**Repo:** `williamblair333/Uncle-J-s-Refinery`  
**Audience:** Claude Code session picking this up cold

---

## What this document is

Anthropic announced three new capabilities at Code with Claude (May 7, 2026): **Dreaming**, **Outcomes**, and **Multi-agent orchestration**. Two are now in public beta; Dreaming is in research preview. All three map cleanly onto infrastructure Uncle J's Refinery already has. This document defines exactly where each feature plugs in, what needs to be built, what already exists, and what the desired end state looks like.

Do not start coding without reading the full document first. Each section ends with an explicit task list.

---

## Feature 1 — Dreaming

### What it is (from the article)

Dreaming is a **scheduled batch process** — not a live session capability. It reviews an agent's past sessions and memory stores, extracts patterns across them, and writes the results back as plain-text notes and structured "playbooks" that future sessions reference. It is explicitly *not* weight modification. It surfaces things no single session can see: recurring mistakes, workflows multiple agents converge on independently, shared preferences across a team of agents.

Key implementation detail from Anthropic: it runs on a schedule ("overnight"), is triggered manually from the developer console, and produces output that is human-inspectable before future sessions consume it.

### What Uncle J's already has

| Dreaming needs | Uncle J's already has |
|---|---|
| Full session traces with tool calls, timings, token counts | Langfuse Stop hook — every turn traced |
| Long-term memory store that agents can write to and query | MemPalace with semantic search |
| A scheduled task runner | stack-alerts cron infrastructure (`lib/feature-helpers.sh`, `scripts/check-stack-freshness.sh`) |
| A place to store playbooks agents will read next session | `~/.claude/CLAUDE.md` (global policy) and per-project `CLAUDE.md` |
| A trigger mechanism | healthcheck.sh pattern + `/health` slash command |

The gap: **no component currently reads Langfuse traces, synthesizes learnings, and writes them back to MemPalace or CLAUDE.md.**

### Integration target

Create `features/dreaming/` with the following:

```
features/dreaming/
├── install.sh          # registers dreaming-agent skill + cron entry
├── README.md
├── dream.sh            # main entry point — callable manually or by cron
└── skills/
    └── dream-synthesizer/
        └── SKILL.md    # Claude Code skill that does the actual synthesis
```

#### `dream.sh` — what it must do

1. **Query Langfuse** for traces since the last dreaming run. Use the Langfuse REST API (`GET /api/public/traces`) with the LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY already in `~/.claude/settings.json` env block. Filter by `tags` or `metadata.session_date`. Write last-run timestamp to `state/dreaming-last-run.txt`.

2. **Format traces** into a structured prompt. Each trace = one session. Extract: task description (first user turn), tools called in order, errors encountered, final outcome (success/fail/partial), token counts. Strip PII. Keep it under ~8k tokens total — use jdocmunch-style section slicing if the trace dump is large.

3. **Invoke Claude** via `claude -p` (non-interactive) with the `dream-synthesizer` skill. The skill prompt instructs it to:
   - Identify recurring error patterns
   - Identify workflows that succeeded consistently
   - Identify tool sequences that were wasteful (high token cost, low signal)
   - Produce output in two sections: `## Recurring Mistakes` and `## Proven Playbooks`

4. **Write output to MemPalace.** Each playbook = one `mempalace add` call with a descriptive key. Each mistake = one entry tagged `mistake`. This makes them retrievable by the `prior-art-check` skill on the next non-trivial task.

5. **Optionally append a summary** to `~/.claude/CLAUDE.md` under a `## Dreaming Notes (auto-generated)` section header. The section must be idempotent — overwrite on each dreaming run, do not accumulate.

6. **Log the run** to `state/dreaming.log` with timestamp, trace count processed, entries written to MemPalace, and any errors.

#### `dream-synthesizer/SKILL.md`

Follow the existing skill format used in `skills/prior-art-check/SKILL.md` and `skills/judge/SKILL.md`. The skill is invoked with a block of formatted session traces and must return structured markdown only — no conversational preamble. Claude Code will parse the output sections directly.

#### Cron schedule

Add to the dreaming install.sh using the existing `lib/feature-helpers.sh` cron helper. Default: 2 AM daily. Make it configurable via an env var `DREAMING_CRON_SCHEDULE` written to `state/dreaming.env`.

#### Manual trigger

Add a `/dream` slash command at `~/.claude/commands/dream.md` that runs `dream.sh` on demand inside a Claude Code session. Mirror the pattern of the existing `/health` command.

#### Tasks

- [ ] Create `features/dreaming/install.sh`
- [ ] Create `features/dreaming/dream.sh` with Langfuse query, Claude invocation, MemPalace write, CLAUDE.md append
- [ ] Create `features/dreaming/skills/dream-synthesizer/SKILL.md`
- [ ] Add `/dream` slash command to `~/.claude/commands/dream.md`
- [ ] Add `state/dreaming-last-run.txt` to `.gitignore` (already has a `state/` entry — verify it covers this)
- [ ] Add dreaming section to `docs/STACK.md`
- [ ] Update `verify.sh` to check that dreaming cron entry exists when `DREAMING_ENABLED=1`

---

## Feature 2 — Outcomes

### What it is (from the article)

Outcomes lets developers define a **rubric** — a success standard — and then a separate **grader agent** evaluates the working agent's output against that rubric in a fresh, independent context window. The grader identifies gaps. The working agent takes another pass. Loop continues until the rubric is satisfied. Key design principle: the grader runs in a *fresh* context, isolated from the working agent's accumulated reasoning. This is what prevents the grader from inheriting the same blind spots.

Anthropic's stated rationale: "You will get higher success if you give that output to a fresh Claude and say, 'what bugs do you see?'" A long-running thread's attention degrades; a fresh context catches what the long thread misses.

### What Uncle J's already has

The `judge` skill is the closest existing analog. It spawns a code-reviewer subagent before Edit/Write operations and requires structural evidence before approving. This is outcomes-adjacent but not outcomes — it's a one-shot gate, not an iterative loop with a rubric.

| Outcomes needs | Uncle J's already has |
|---|---|
| Rubric definition format | Nothing yet |
| Grader agent with fresh context | `judge` skill (one-shot, no rubric) |
| Iterative loop until rubric satisfied | Ralph Wiggum loop (but exit criteria are code-quality metrics, not rubrics) |
| Rubric-gap reporting back to working agent | Nothing yet |

### Integration target

Extend the existing `judge` skill and Ralph harness rather than building from scratch.

#### Step 1 — Rubric format

Define a standard rubric format as a markdown file. Store at `skills/outcomes/RUBRIC.md.template`. A rubric is a numbered list of criteria, each with:
- Criterion description
- Pass condition (what "met" looks like)
- Fail condition (what "not met" looks like)
- Weight: `required` or `preferred`

All `required` criteria must pass. `preferred` criteria are surfaced in the gap report but do not block completion.

Example rubric entry:
```markdown
### 1. Tests pass
- Pass: `pytest` exits 0 with no skips
- Fail: any test failure or skip
- Weight: required
```

Store project-specific rubrics at `.claude/outcomes/rubric.md` within each project repo.

#### Step 2 — Extend `judge` skill into an outcomes loop

Create `skills/outcomes/SKILL.md`. This skill:
1. Receives: the working agent's output + the rubric path
2. Evaluates each criterion independently in its own reasoning block
3. Returns: a structured gap report — which criteria passed, which failed, specific remediation instructions for each failure
4. Never suggests "try harder" — it must name the specific gap and the specific fix

The skill must be invokable from Ralph's loop as an exit-gate check, not just on Edit/Write.

#### Step 3 — Wire into ralph-harness.sh

Add a `--rubric` flag to `ralph-harness.sh`. When provided:
- After each Ralph loop iteration, invoke the outcomes skill with the current output and rubric
- If all `required` criteria pass, exit the loop (supplement existing exit criteria: get_pr_risk_profile, get_untested_symbols, PRD DONE)
- If any `required` criteria fail, inject the gap report as the next Ralph prompt
- Cap at `OUTCOMES_MAX_ITERATIONS` (default: 5, configurable) to prevent infinite loops
- Log each grader verdict to Langfuse with a `outcomes_grade` tag so dreaming can later analyze grader patterns

#### Tasks

- [ ] Create `skills/outcomes/RUBRIC.md.template`
- [ ] Create `skills/outcomes/SKILL.md` (rubric-aware grader agent)
- [ ] Update `ralph-harness.sh` to accept `--rubric` flag and outcomes loop
- [ ] Add `OUTCOMES_MAX_ITERATIONS` env var to settings.json env block during install
- [ ] Update `prd-template.md` to include a `## Success Rubric` section
- [ ] Update `docs/RELIABILITY.md` with outcomes loop documentation
- [ ] Update `verify.sh` to check that outcomes skill exists

---

## Feature 3 — Multi-agent orchestration

### What it is (from the article)

A lead agent decomposes a large task into subtasks and delegates each to a specialist agent — each with its own model, system prompt, tools, and **independent context window**. The design principle: isolated context per sub-agent produces better results than one agent holding all complexity in one thread. Parallel agents are best for **investigation** tasks — situations where large amounts of context will ultimately be discarded and only the result matters.

Alex Albert's heuristic from the article: "If you're trying to answer a specific question, you don't need all the search results from the areas where it didn't find the answer. You just need the answer." Spin up disposable sub-agents for retrieval; bring only the answer back to the main thread.

### What Uncle J's already has

| Multi-agent needs | Uncle J's already has |
|---|---|
| Sub-agent spawning | Claude Code `claude -p` subprocess + jCodeMunch `SubagentStart` hook |
| Specialist tool assignment per agent | MCP server registration at user scope (all 7 servers available to any subprocess) |
| Result aggregation | Nothing structured yet |
| Lead agent decomposition logic | Nothing yet — Ralph runs as a single loop |
| Trace visibility per sub-agent | Langfuse Stop hook (but not tagged by agent role) |

### Integration target

Extend Ralph harness with a `--decompose` mode and add an orchestrator skill.

#### Step 1 — Orchestrator skill

Create `skills/orchestrator/SKILL.md`. When invoked, this skill:
1. Receives a PRD or task description
2. Analyzes it for parallelizable subtasks (research tasks, retrieval tasks, independent implementation units)
3. Outputs a structured task manifest: JSON array of `{ role, task, tools_needed, context_needed, output_format }`
4. Assigns tool access per role: code tasks get jCodeMunch + Serena; data tasks get jDataMunch + DuckDB; doc tasks get jDocMunch + Context7; memory tasks get MemPalace

#### Step 2 — Multi-agent ralph-harness mode

Add `--decompose` flag to `ralph-harness.sh`. When set:
1. Invoke orchestrator skill to produce task manifest
2. For each task in manifest, spawn a `claude -p` subprocess with:
   - Role-specific system prompt (drawn from orchestrator output)
   - Only the tools needed for that role (pass as env var or MCP filter)
   - Task-specific context (use jCodeMunch/jDocMunch to pre-fetch relevant context before spawning — do not give the sub-agent the whole codebase)
3. Run subtasks in parallel where `context_needed` fields don't overlap; serialize where they do
4. Collect results; pass to a synthesis agent that merges outputs and produces the final deliverable
5. Run outcomes grader on the merged result if `--rubric` is also provided

#### Step 3 — Langfuse tagging

Update `langfuse_hook.py` (at `~/.claude/hooks/langfuse_hook.py`) to read an env var `AGENT_ROLE` and attach it as a Langfuse trace tag. `ralph-harness.sh` sets this env var when spawning sub-agents. This makes multi-agent runs visible in Langfuse as a tree of role-tagged traces rather than an undifferentiated stream. Dreaming can then analyze by role.

#### Step 4 — SubagentStart hook alignment

jCodeMunch's `SubagentStart` hook already fires when a sub-agent starts. Verify it enforces the retrieval-first routing policy on sub-agents the same way it does on the main agent. If it doesn't, add a role-check: if `AGENT_ROLE` is set, enforce the role's designated tools only.

#### Tasks

- [ ] Create `skills/orchestrator/SKILL.md`
- [ ] Add `--decompose` flag to `ralph-harness.sh` with parallel subprocess spawning
- [ ] Update `langfuse_hook.py` to read and tag `AGENT_ROLE`
- [ ] Audit `SubagentStart` hook to confirm role-scoped tool enforcement
- [ ] Add `AGENT_ROLE` handling to install.sh settings.json env block
- [ ] Update `docs/STACK.md` with orchestrator + multi-agent section
- [ ] Update `prd-template.md` with `## Agent Decomposition` optional section

---

## How the three features compose (the continuous improvement loop)

This is the end state the Anthropic demo illustrated and what Uncle J's should target:

```
Ralph (--decompose --rubric)
│
├── Orchestrator skill → task manifest
│
├── Parallel sub-agents (role-scoped, isolated context)
│   ├── Code agent (jCodeMunch + Serena)
│   ├── Data agent (jDataMunch + DuckDB)
│   └── Doc agent (jDocMunch + Context7)
│
├── Synthesis agent → merged deliverable
│
├── Outcomes grader (fresh context, rubric-aware) → gap report
│   └── Loop until rubric satisfied or OUTCOMES_MAX_ITERATIONS
│
└── Langfuse Stop hook → trace everything, tag by role
        │
        └── Dreaming (nightly) → reads traces → writes playbooks to MemPalace
                                                → appends to CLAUDE.md
                                                → prior-art-check reads these next session
```

Every iteration improves the next. The loop is observable at every stage via Langfuse. The playbooks are human-readable and human-correctable before they influence future sessions.

---

## Build order

Do these in order. Each stage is independently testable.

1. **Dreaming** — highest leverage, uses existing infrastructure (Langfuse + MemPalace). No changes to ralph-harness. Self-contained in `features/dreaming/`.
2. **Outcomes** — extends judge skill and ralph-harness. Requires ralph-harness familiarity but no new dependencies.
3. **Multi-agent** — most complex. Requires outcomes to be working first (grader is the exit gate for the orchestration loop). Requires Langfuse tagging update.

---

## Constraints and guardrails to preserve

Do not break or bypass any of these during integration:

- **jCodeMunch PreToolUse/PostToolUse hooks** — sub-agents must go through them. Do not bypass with `--dangerously-skip-permissions` in production sub-agent spawns.
- **dwarvesf guardrails** — secret scanner and prompt-injection defender must remain active for sub-agents. Pass the same hook env to subprocesses.
- **Bash-matcher destructive command blocks** — sub-agents must not be able to bypass them via a `--decompose` invocation.
- **MemPalace writes from dreaming** — must use the venv interpreter (`.venv/bin/mempalace`), not system Python.
- **Langfuse SDK version** — must stay on `langfuse>=3.0,<4`. Do not upgrade to v4 during this integration work.
- **MCP timeout** — `MCP_TIMEOUT=60000` in settings.json. Sub-agent spawns inherit this via env; verify it propagates.

---

## Files to create (summary)

```
features/dreaming/
├── install.sh
├── dream.sh
├── README.md
└── skills/dream-synthesizer/SKILL.md

skills/outcomes/
├── RUBRIC.md.template
└── SKILL.md

skills/orchestrator/
└── SKILL.md

~/.claude/commands/
└── dream.md          (slash command)
```

Files to modify:
- `ralph-harness.sh` — add `--rubric` and `--decompose` flags
- `prd-template.md` — add Success Rubric and Agent Decomposition sections
- `~/.claude/hooks/langfuse_hook.py` — add AGENT_ROLE tagging
- `docs/STACK.md` — add dreaming, outcomes, orchestrator entries
- `docs/RELIABILITY.md` — add outcomes loop documentation
- `verify.sh` — add dreaming cron check, outcomes skill check
- `.gitignore` — add `state/dreaming-last-run.txt` if not already covered

---

## Reference

- VentureBeat article: https://venturebeat.com/technology/anthropic-introduces-dreaming-a-system-that-lets-ai-agents-learn-from-their-own-mistakes
- Anthropic Claude Managed Agents: https://docs.anthropic.com/managed-agents (check for dreaming API docs as research preview matures)
- Langfuse REST API (for trace query in dream.sh): `GET /api/public/traces` — auth via LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY already in env block
- Existing slash command pattern to mirror: `~/.claude/commands/health.md`
- Existing cron helper to use: `lib/feature-helpers.sh` → `write_cron_entry()`

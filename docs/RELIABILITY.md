# Reliability layer reference

The core stack (jMunch trio + Serena + Context7 + DuckDB MCP servers, plus the
offline memweave memory CLI) gives Claude the *right tools*. The reliability layer
makes sure Claude *actually uses them correctly*. Four components:

| Component                     | What it does                                                      | When to turn off            |
| ----------------------------- | ----------------------------------------------------------------- | --------------------------- |
| prior-art-check skill         | memweave (mw_search.py) lookup BEFORE the first real tool call every session | never; it's just a lookup   |
| judge skill                   | Gathers blast radius + PR risk, then delegates to specialist agents | for throwaway prototyping  |
| Specialist agents (6)         | Code review, security, silent failures, planning, architecture, TDD — each with precise trigger conditions | individually per task type |
| Ralph harness                 | while-true loop that only stops when risk is low + PRD is DONE    | only in live runs           |
| dwarvesf claude-guardrails    | Block pasted secrets, scan tool output for prompt-injection       | never (low cost, high value)|
| Superpowers plugin            | 20+ skills: brainstorm, systematic-debug, TDD, verify-before-done | if total skill count > 25   |
| Ralph Wiggum plugin           | /ralph slash command (Anthropic official version)                 | --                          |
| outcomes skill (--rubric)     | Rubric-aware grader in fresh context after each Ralph iteration   | when not using --rubric flag |
| refinery-doctor.sh            | Config drift detection: env key renames, stale MCP scopes, CLAUDE.md sync, placeholder values; `--fix` applies atomic migrations | after fresh install confirms all green |
| Telegram multi-agent routing  | `/work <msg>` → project-context Claude (proj_root cwd, CLAUDE.md loaded); unqualified → restricted default (cwd=/tmp, disclosure ban); config in `config/telegram-agents.toml`; hardcoded fallback if TOML missing | never; missing TOML = safe restricted-only mode |
| ralph / Telegram billing      | Strip `ANTHROPIC_API_KEY` + `ANTHROPIC_AUTH_TOKEN` from subprocess env so `claude -p` uses OAuth subscription auth (Agent SDK credit, effective 2026-06-15: Pro=$20/mo, Max5x=$100/mo, Max20x=$200/mo); `--use-api` flag restores API billing for heavy parallel runs | never strip before 2026-06-15 |
| session-status-briefing skill | Step 3 runs `git fetch origin main && git log HEAD..origin/main` — reports if local is behind remote before any work starts (stale-code detection); fetch failure is surfaced via 2>&1, not swallowed | never; offline-safe (fetch error shown, briefing continues) |

## How the pieces compose

```
── SESSION START ──────────────────────────────────────────────────────
SessionStart hooks
   ├── healthcheck context injected into session banner
   └── skill-link: per-project skills symlinked to ~/.claude/skills/

── PER-MESSAGE LOOP ───────────────────────────────────────────────────
user message
   │
   ▼
UserPromptSubmit: scan-secrets.sh      <- blocks pasted credentials
   │                                      (API keys, tokens, PEM blocks)
   ▼
prior-art-check skill                  <- "have we solved this?"
   │   memweave hit? surface prior decisions as context
   ▼
CLAUDE.md routing policy               <- which MCP tool fits?
   │
   ▼
MCP tools / main work                  <- jcodemunch / serena / jdatamunch
   │                                      jdocmunch / context7 / duckdb (+ memweave CLI)
   ▼
PreToolUse hooks                       <- enforce-docs, scan-commit,
   │                                      bash-guard rules, jcodemunch pre-hook
   ▼
[Edit or Write?]──no──────────────────────────────────────────────┐
   │ yes                                                           │
   ▼                                                              │
judge skill                            <- get_blast_radius,        │
   │                                      get_changed_symbols,     │
   │                                      get_pr_risk_profile      │
   ▼                                                              │
specialist agents (risk-based)         <- see trigger matrix below │
   │   verdict: approve / concerns / block                        │
   ▼                                                              │
tool executes ◄────────────────────────────────────────────────────┘
   │
   ▼
PostToolUse (Edit/Write): jCodemunch auto-reindex
PostToolUse (Read/WebFetch/Bash/mcp): injection defender
   │
   ▼
response to user

── SESSION END ────────────────────────────────────────────────────────
Stop hooks (in order)
   ├── Langfuse trace submitted                       (global settings.json)
   ├── session-end-check.sh --stop-hook               (global — doc gate)
   ├── unpushed-warn.sh + pr-check.sh                 (global — reminders)
   ├── session-notify.sh  (Telegram, opt-in)          (project settings.json)
   ├── memweave/sync_memory.sh '' 15  (incremental ingest of recent transcripts)
   └── skill-suggest.sh + skill-link unlink
```

All gates can fire in under 15 seconds for a typical coding turn.
Ralph runs the per-message loop on every iteration.

## memweave memory freshness

Project memory routing (`CLAUDE.md` §4) resolves "have we solved this before?" to
`scripts/memweave/mw_search.py` (offline ONNX semantic+BM25, read-only) over the store below.

The offline memweave store at `~/.uncle-j-memory` is the **cross-project** memory store — it
holds every project's transcripts under `~/.claude/projects` (markdown corpus + sqlite index),
not just this project's. (The `uncle-j` name is legacy.) It's kept current by two callers of
`scripts/memweave/sync_memory.sh`, which is `flock -n`-guarded (`/tmp/memweave-sync.lock`) so the
two can never race the single sqlite writer:

| Caller | Schedule | Scope |
|--------|----------|-------|
| `uncle-j-memweave-sync` cron | 02:30 nightly (`nice -19`) | `--all` — full cross-project export+index (every project) |
| Stop-hook (`# uncle-j-memweave-sync`) | every session end (`async`) | incremental — this project, `LIMIT 15` most-recent transcripts |

Both redirect to `state/memweave-sync.log`; the script logs to stdout/stderr only (callers own
the destination). The store is fully reconstructable from the markdown corpus (memweave M2
crash-recovery: `rm` the index → byte-identical rebuild), so an interrupted sync is recoverable.

**Prerequisite:** the py3.12 `.venv-memweave` must exist (memweave requires ≥3.12; it can't live
in the 3.11 project venv). A missing venv makes `sync_memory.sh` exit 1 with a logged error —
`install.sh` registers the cron but does **not** yet build this venv, so a fresh provision needs
it created by hand until venv bootstrap is folded in (Phase 3/4).

**Follow-up (open):** no freshness alarm yet — failures land in the log but aren't alerted, and a
hung export holds the flock so later runs cleanly skip while the store ages. Add a memweave
freshness probe to `healthcheck.sh` (assert index mtime < 48h).

## What each component buys you

### prior-art-check

Answers the question "does the agent ask itself 'have we solved this
before' before working?" with **yes, now it does**. Without this skill,
memweave is a CLI the agent *could* run but usually won't. With it,
the agent checks prior work on every non-trivial prompt via `mw_search.py`.
Zero cost on an empty store; 1-2 second overhead on a warm one.

Step 3b (staleness filter): any memweave hit containing `pending`,
`awaiting`, `needs`, `consider`, `not yet`, `TODO`, or `FIXME` must be
verified against current source before being reported as fact. Prevents
the failure mode where a memory entry says "PR awaiting review" long after
the PR has merged and the fix is running. Complements the healthcheck
staleness advisory scan which surfaces the same entries at session start
(warning-only, not a failure).

### judge

Always fires before any non-trivial Edit or Write. Two responsibilities:

1. **Gather structural evidence** — `get_blast_radius`, `get_changed_symbols`, `get_untested_symbols`, `get_pr_risk_profile` from jCodemunch
2. **Delegate to specialist agents** based on that evidence (see trigger matrix below)

Catches the four classic hallucination patterns:

1. Invented functions (call `foo.bar()` where `bar` doesn't exist)
2. Invented imports (import a module that isn't a dep)
3. Wrong signature (skip required parameter)
4. Missed callers (rename symbol, forget to update all sites)

**Skip conditions:** typos, whitespace/formatting-only, comment-only edits, single-variable renames with no logic change, changes already reviewed in the same turn.

### Specialist agent trigger matrix

Six agents in `global-agents/`, symlinked to `~/.claude/agents/`. The judge delegates based on change type. Multiple agents can fire on the same change.

| Agent | Spawn when | Skip when |
| ----- | ---------- | --------- |
| `code-reviewer` | Edit/Write changes function logic, adds/removes functions or classes, modifies control flow, touches API or data model | Typos, whitespace/formatting, comment-only, single-variable rename with no logic change |
| `security-reviewer` | Edit/Write touches user input handling, auth/session/token code, API endpoints, file I/O with user-controlled paths, DB queries, crypto/hashing, payment flows, subprocess/shell execution | Pure UI layout, documentation, config that doesn't touch auth, input, or data paths |
| `silent-failure-hunter` | Edit/Write touches exception/error handlers, async functions, network calls, file I/O, DB operations, subprocess execution, or code using try/except / .catch() / \|\| true / default fallbacks; any new function interacting with an external system | Pure logic, data transformation, UI code with no I/O or error-handling paths |
| `planner` | Spawned BEFORE code when a request spans multiple files, introduces a new feature, or requires phased delivery ("add X feature", "implement Y", "refactor Z across the codebase") | Single-function bug fixes, small contained patches, requests where implementation path is already clear |
| `architect` | Structural decisions — new module/service boundaries, data model design, technology choices, scalability trade-offs, any cross-service or cross-module design question | Routine feature implementation where structure is already established |
| `tdd-guide` | Spawned BEFORE implementation of any new function, class, or module; bug fixes requiring new test coverage; refactors that change observable behavior | Editing existing passing tests, fixing comments/docs, formatting-only changes with no behavior change |

### Ralph harness (our version vs. the plugin)

Anthropic's Ralph plugin (`/ralph`) is the standard Huntley pattern:
loop the agent on a prompt file until it says done.

Our harness (`ralph-harness.sh`) adds structural done-gates:

- `get_changed_symbols` — confirms something actually moved
- `get_untested_symbols(changed_only=true)` — blocks if new code has
  no tests
- `get_pr_risk_profile` — blocks if composite risk exceeds threshold

So the loop only exits when BOTH the model says "done" AND the stack's
structural view agrees. Solves the classic Ralph failure mode where
the model confidently declares victory on a broken change.

Pick the plugin for exploratory runs; pick the harness for anything
you plan to commit.

### Outcomes grader

The `outcomes` skill runs in a **fresh context window** — it has not seen
the working agent's accumulated reasoning. This is the point: a long thread
develops blind spots; a fresh context catches them.

Invoked automatically when `ralph-harness.sh --rubric <path>` is used.
After each iteration:

1. Reads the rubric file (criteria with pass/fail conditions and weights)
2. Evaluates each criterion against the PRD Progress section and repo state
3. Returns a JSON verdict: `pass` or `fail` with specific remediation steps
4. If `fail`, injects the gap report as context for the next iteration

Loop exits only when BOTH the structural done-gate (risk + untested) AND
the rubric grader agree the work is complete. Cap: `OUTCOMES_MAX_ITERATIONS`
(default 5). Set in `~/.claude/settings.json`'s `env` block — written
automatically by `install-reliability.sh` on fresh installs. Override per
run with `export OUTCOMES_MAX_ITERATIONS=N` before calling the harness.

The rubric format lives at `global-skills/outcomes/RUBRIC.md.template`.
Project rubrics go at `.claude/outcomes/rubric.md` within the project repo.

### Superpowers

The single biggest agent-reliability upgrade available in 2026.
20+ skills enforcing real-engineering discipline:

- `brainstorming` — forces requirements clarification before code
- `systematic-debugging` — 4-phase root-cause process, no speculative
  fixes until evidence is gathered
- `test-driven-development` — RED-GREEN-REFACTOR on new code
- `verification-before-completion` — agent must prove the fix works
  before claiming success
- `requesting-code-review` — well-composed hand-off to reviewer
  subagents (pairs with our judge skill)

Caveat from the Claude Code community: total active skill count matters
for context budget. Best practice is 20-25 active skills max; more than
that causes skill-selection bias. Superpowers adds 20+ on its own, so
after installing it, remove skills you don't actually use.

### dwarvesf/claude-guardrails

Security layer, hooks-based:

- **UserPromptSubmit secret scanner** — before your prompt reaches the
  model, scans it for live AWS keys, GitHub/Anthropic/OpenAI tokens,
  PEM blocks, BIP39 phrases. Blocks and warns. Prevents both model
  exposure and session-log leakage.
- **PostToolUse injection scanner** — scans Read / WebFetch / Bash
  output for known prompt-injection patterns. Warns (doesn't block)
  so legitimate security content still works.

Based on Trail of Bits + Lasso research + Anthropic's official security
docs. Low overhead. Worth keeping on always.

## Tier 2 — mentioned, not installed

If you want more later, these are the next things worth adding:

- **Langfuse** (https://langfuse.com) — agent observability. Native
  Claude Agent SDK integration. Every tool call and completion becomes
  an OpenTelemetry span. Self-hostable via Docker. 19k stars, MIT
  license. Best for "why did my agent do X two sessions ago."
- **Anthropic-Cybersecurity-Skills** (mukul975) — 754 skills mapped to
  MITRE ATT&CK / NIST CSF. Overkill unless you work in security.
- **Verdent Review Subagent** — commercial. Cross-validates a change
  with Claude + Gemini + GPT-5.2 concurrently. Expensive per review;
  use on high-stakes PRs only.

## Operational notes

The SessionStart staleness check scans `MEMORY.md` for stale tracking entries (`pending`, `awaiting`, `needs <verb>`, etc.) and flags them at session start so they're verified before being reported as current fact.

`session-end-check.sh` behaviour is covered by `tests/test_session_end_check.py` (10 tests, job 5 in `ci.yml`).

(memweave memory operational details — freshness, store layout, recovery — are in the "memweave memory freshness" section above. mempalace was decommissioned 2026-06-13; with it gone, the `chromadb==1.5.8` HNSW-corruption-workaround pin + `chroma-hnswlib` dep were also removed from `pyproject.toml` — chromadb was a mempalace-only transitive dependency.)

---

## Skills

Skills live in `global-skills/` and are symlinked to `~/.claude/skills/` by `install-reliability.sh`. Any directory added to `global-skills/` is automatically picked up — no hardcoded list to maintain.

The `auto-maintain-commit-and-deploy` skill documents the pattern: dynamic glob replaces hardcoded name lists, and `git commit` is coupled with an immediate symlink pass so new skills are live before the next session.

---

## Disable / uninstall

```bash
# Remove our skills
rm -rf ~/.claude/skills/prior-art-check ~/.claude/skills/judge

# Remove dwarvesf guardrails (hooks get merged into settings.json; you
# need to edit that manually if you want to revert)
rm -rf /opt/proj/Uncle-J-s-Refinery/claude-guardrails

# Remove Superpowers / Ralph
# Inside claude: /plugin uninstall superpowers
# Inside claude: /plugin uninstall ralph-wiggum
```


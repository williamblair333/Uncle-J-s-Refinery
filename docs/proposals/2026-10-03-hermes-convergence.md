# Proposal: Converge Uncle J's Refinery onto Hermes Agent as a runtime

| | |
|---|---|
| Date | 2026-10-03 |
| Status | Draft — decision requested |
| Author | Claude (session with the repo owner) |
| Supersedes | Nothing. Revises the assumptions in `PORTING.md` (see §4.3) |
| Hermes ref inspected | `NousResearch/hermes-agent@f4d3e626` (main, 2026-10-03), shallow clone |

---

## 1. Summary

Keep the Refinery's best parts. Stop maintaining the parts Hermes Agent already ships.
Make the model behind the agent swappable: Claude subscription, Claude API, any cloud
model, or a local model.

The recommendation is **not a fork and not a big-bang migration.** It is three moves:

1. **Extract a harness-neutral core** from this repo: retrieval MCP servers, memweave,
   skills, guardrail hooks, routing policy and the dreaming loop. That core is the
   asset that compounds. Today it is wired into Claude Code specifically.
2. **Run Hermes beside the Refinery** as a second runtime. Install that core into
   Hermes through Hermes's own extension points: MCP, Claude-Code-compatible shell
   hooks, skills, memory-provider plugins and cron. Measure it against the Refinery
   on real work.
3. **Retire duplicated Refinery plumbing** (Telegram gateway, notify, Ralph cron)
   only where Hermes wins on the standing test.

On the Claude subscription: Hermes cannot use the base Max allowance today, and
the terms around third-party use of subscription credentials have moved several
times in 2026. The safe path keeps **Claude Code itself** as the subscription
runtime. Hermes drives everything else. §6 has the options and the one that needs a
terms check first.

---

## 2. The goal this serves

From `README.md` → *Mission*, in priority order: **Right → Cheap (in total) →
Inventive → Local.** Standing test: every component pays for itself measurably, or
it goes.

From the owner, stated 2026-10-03:

> The ultimate goal is a super intelligent LLM(s) run locally that is the most
> efficient it can possibly be doing whatever I want or need. Efficient meaning the
> cheapest hardware possible. … Ultimately helping me be the most productive in all
> the ways and also teaching me to be the best human (be happy and support yourself).

As a spec: **maximize correct, useful work per dollar of hardware, tokens and
attention, moving steadily toward local models, without losing accuracy, and
growing the owner's own capability rather than replacing it.**

The connection to this proposal:

- The harness changes every few months. The models change faster. The **durable
  asset** is the accumulated context: memory corpus, skills, policy, guardrails and
  extracted playbooks. The architecture should make that asset portable across
  harnesses and models.
- Local models need two things the Refinery lacks: a runtime that can drive them,
  and difficulty routing so small models only get small jobs. Hermes ships both.
- Upkeep is a cost under "Cheap — in total". Every cron job, homegrown poller and
  version-pinned paragraph in `CLAUDE.md` is operator attention.

---

## 3. What was verified (and what changed since the last comparison)

The 2026-05-22 competitive analysis (`CHANGELOG.md`; plan in
`docs/superpowers/plans/2026-05-22-competitive-gap-closure.md`) concluded that the
Refinery's approval-gated skill promotion was "explicitly safer than Hermes's
auto-commit pattern." **Hermes has since closed most of that gap.**

The table below was read from Hermes source and docs at `f4d3e626`, not from
marketing pages.

| Capability | Hermes today (verified) | Refinery equivalent | Consequence |
|---|---|---|---|
| Approval-gated skill writes | `skills.write_approval: true` stages every `skill_manage` write to `~/.hermes/pending/skills/`. `/skills pending`, `/skills diff`, `/skills approve`, `/skills reject`, also over messaging. Same gate for memory: `memory.write_approval` | `skill-suggest.sh` → Telegram approve → `scan_skill_body` → promote | Moat gone. Use Hermes's gate and keep `scan_skill_body` as an extra scanner |
| Skill content scanning | `skills.guard_agent_created` heuristic scanner. Project skills are scanned and **quarantined** if dangerous, with a content-hash cache | `scripts/lib/tg_security.py::scan_skill_body` | Parity. Ours can run as a `pre_tool_call` hook on `skill_manage` |
| Skill library hygiene | **Curator**: usage tracking, stale (14d) → archived (30d), LLM consolidation review, never deletes, dry-run | `check_skill_compliance` in `healthcheck.sh` | Hermes ahead |
| Tool-call veto hooks | `pre_tool_call` can **block**, **modify args** or **escalate to approval**. Shell hooks are declared in `config.yaml` | Claude Code PreToolUse hooks (`hooks/discipline/*`, `hooks/pre-mortem-guard/*`, guardrails) | **Hard-blocking guardrails can move.** This was the biggest open risk |
| Claude Code hook compatibility | Shell hooks accept Claude Code's stdout shape (`{"decision":"block","reason":…}`), **exit code 2 = block**, and `fail_closed`/`failClosed` | Our hooks are written to that contract | Hooks port with **tool-name remapping only** (see §5.3) |
| Context injection | `pre_llm_call` returns `{"context": "..."}` | `UserPromptSubmit`-style hooks | Parity |
| Stop gate | `pre_verify` accepts Claude Code's Stop shape and keeps the agent going | Stop hooks | Parity |
| Observability | Bundled **Langfuse plugin** (opt-in): `HERMES_LANGFUSE_*`, self-hosted URL supported | `install-langfuse.sh` plus a Claude Code Stop hook | Use the bundled plugin. `PORTING.md` §7's hand-written plugin is obsolete |
| Memory extension | Memory-provider plugin interface: system-prompt context, per-turn prefetch, turn sync, session-end extraction, provider tools | memweave (CLI only) | memweave becomes a provider. Prefetch gives prior-art checks for free |
| Cross-session search | `session_search` (SQLite FTS5) | memweave transcript corpus | Complementary |
| Scheduling | Built-in cron with delivery to any platform | `ralph-cron`, `stack-alerts`, gateway pollers | Hermes ahead |
| Messaging | Telegram, Discord, Slack, WhatsApp, Signal, email and more | Telegram only, homegrown poller | Hermes ahead |
| Model providers | 40+ including Ollama, vLLM, llama.cpp, SGLang, LM Studio, custom OpenAI-compatible endpoints | Claude only | Hermes ahead |
| Cheap-model routing | `auxiliary.*.provider` sends compression, titles and vision to a different model. Fallback providers | none | First step toward the difficulty router |
| External agent as runtime | **Codex app-server runtime**: Hermes hands whole turns to Codex CLI on a ChatGPT subscription. Hermes stays the shell (sessions, gateway, memory, skill review) | `telegram-gateway-poll.sh` shells to `claude --print` | **The template for a Claude Code runtime** (§6) |
| Trajectory export | `batch_runner.py`, `trajectory_compressor.py` | Langfuse traces, no export | Plumbing exists for future distillation |

**What Hermes still lacks, and stays the Refinery's contribution:**

1. Structural retrieval for each kind of content: jCodeMunch, jDocMunch,
   jDataMunch, Serena, plus the absence-vs-degraded verdict contract. Hermes's
   default retrieval is grep and file reads.
2. memweave's unbounded local markdown corpus, including the Obsidian vault mirror.
   Hermes's built-in memory is 2,200 + 1,375 characters by design.
3. Dreaming: nightly trace replay into *Recurring Mistakes* and *Proven Playbooks*.
4. The discipline layer: pre-mortem guard, push guard, grep guard, judge, gttp,
   verification-before-completion, and a mission that ranks accuracy first.
5. The self-healing health checks (`healthcheck.sh`, `refinery-doctor.sh`, FTS5
   and HNSW guards), retargeted at the new runtime.

---

## 4. Options considered

| Option | Description | Verdict |
|---|---|---|
| A. Status quo | Keep the Refinery on Claude Code only | Rejected. No path to local models, and the plumbing upkeep stays |
| B. Fork Hermes and merge the Refinery into it | One codebase | **Rejected.** Hermes is very active (~17K files). Keeping a fork in sync is permanent attention debt, the opposite of "Cheap — in total". Every extension point needed already exists without forking |
| C. Execute `PORTING.md` as written | Wholesale migration | Rejected as written. See §4.3 |
| **D. Shared core + two runtimes** | Neutral core. Hermes runtime for any model. Claude Code runtime for the subscription | **Recommended** |
| E. Claude Code + an LLM gateway (LiteLLM) for non-Claude models | Keep one harness. Point `ANTHROPIC_BASE_URL` at a gateway | Fallback only. Claude Code is tuned for Claude, and tool-calling quality through a translation layer to small local models is untested here. No messaging or cron gains |

### 4.1 Why D

- It keeps the asset portable. If a better runtime appears next year, it adopts
  the same core.
- Nothing gets deleted until a measured comparison says so. Rollback is free.
- It uses Hermes's official extension surfaces, so upgrades stay `hermes update`.

### 4.2 Licensing

Hermes is MIT, and the Refinery is AGPL-3.0. Plugins, hooks and MCP servers run as
separate programs or user-installed extensions, so no Hermes code is modified or
redistributed. Keep that boundary. Upstreaming anything to Hermes means
contributing it under MIT, which is your choice per piece. The j*Munch packages
keep their own terms (see `README.md` → *Commercial use*).

### 4.3 What is wrong with `PORTING.md` today

- It predates `write_approval`, the Langfuse plugin, shell hooks, memory-provider
  plugins and the Codex runtime pattern. About half of it rebuilds things Hermes now
  ships.
- Its plugin hook signatures (`on_turn_start`, `on_tool_call`, `on_user_message`)
  are **guesses** and do not match Hermes's `VALID_HOOKS`.
- It pins `claude-sonnet-4-6` and an `ANTHROPIC_API_KEY`, which bills per token.
- Its MCP registration flags are unverified. Hermes uses an `mcp_servers:` block
  in `config.yaml`.

Keep `PORTING.md` as history. This proposal replaces its plan.

---

## 5. Target architecture

```
                     ┌──────────────────────────── shared core (this repo) ───────────────────────────┐
                     │ MCP: jcodemunch · jdocmunch · jdatamunch · serena · context7 · duckdb          │
                     │      memweave-mcp (new)                                                         │
                     │ skills/: agentskills.io SKILL.md (gttp, judge, pre-mortem, prior-art-check, …)   │
                     │ hooks/: Claude-Code-contract scripts, tool names via a mapping table            │
                     │ policy/: ROUTING.md (≤ ~60 lines, model-agnostic) + per-runtime adapters        │
                     │ dreaming/: reads traces from Langfuse (either runtime) or Hermes state.db       │
                     │ health/: healthcheck + doctor, runtime-aware                                     │
                     └───────────────┬───────────────────────────────────────────┬────────────────────┘
                                     │                                           │
              ┌──────────────────────▼────────────┐            ┌─────────────────▼──────────────────────┐
              │ Runtime 1: Claude Code (today)    │            │ Runtime 2: Hermes Agent (new)          │
              │ • Claude subscription quota       │            │ • any provider: API, OpenRouter,       │
              │ • install.sh wiring (unchanged)   │◄──turns────│   Ollama / vLLM / llama.cpp (local)    │
              │                                   │  (Phase 4, │ • messaging, cron, curator, approvals  │
              │                                   │  optional) │ • aux/fallback routing (cheap models)  │
              └───────────────────────────────────┘            └────────────────────────────────────────┘
```

### 5.1 Component port map

Effort: **S** < ½ day, **M** 1–3 days, **L** > 3 days. These are rough estimates.

| Refinery component | Destination in Hermes | Mechanism | Effort | Notes |
|---|---|---|---|---|
| jCodeMunch, jDocMunch, jDataMunch | `mcp_servers:` in `~/.hermes/config.yaml` | stdio MCP, absolute venv paths | S | Same binaries as today |
| Serena, Context7, DuckDB | `mcp_servers:` | `uvx` / `npx` | S | |
| memweave | **memory-provider plugin** `$HERMES_HOME/plugins/memweave/` **plus** a small `memweave-mcp` server | Provider: prefetch → `mw_search`, session-end → append to corpus. MCP server: the same functions for Claude Code | M | The MCP server also benefits Claude Code. Opens the store read-only, like today |
| Routing policy | `SOUL.md` / context files | Distil `CLAUDE.md` to model-agnostic rules | M | The hard part is cutting. Version-pinned patch notes leave the always-loaded prompt. Local models degrade on long system prompts |
| jOutputMunch rules | `SOUL.md` | Paste | S | |
| Skills (`global-skills/*`, `skills/*`) | `skills.external_dirs` or project skill dir, read-only | agentskills.io frontmatter is already the standard here (`docs/skill-frontmatter-standard.md`) | S | ⚠ `skill_manage` **does** patch skills in place under `external_dirs`, so the agent can rewrite our repo's skills. Keep `write_approval: true`, or use a project skill dir, which the curator never modifies. Verify which applies to agent edits |
| Secret scanner, injection defender | `hooks: pre_llm_call` / `post_tool_call` / `pre_tool_call` with `fail_closed: true` | Shell hooks | S–M | Security gates must fail closed |
| `hooks/discipline/*` (push, grep, edit-surface guards), `hooks/pre-mortem-guard/*` | `hooks: pre_tool_call` with matcher | Shell hooks, exit 2 = block | M | Tool-name remap, see §5.3 |
| Bash blocklist (`rm -rf`, pipe-to-shell, push to main) | Hermes dangerous-command approvals **plus** the same `pre_tool_call` hooks | Built-in and shell hooks | S | Belt and braces |
| Skill promotion pipeline | `skills.write_approval: true` + `skills.guard_agent_created: true` + `scan_skill_body` as a `pre_tool_call` hook on `skill_manage` | Built-in and shell hook | S | Retire the Telegram promotion path once parity is shown |
| Langfuse | Bundled plugin, `HERMES_LANGFUSE_BASE_URL` → existing self-hosted instance | Config | S | One Langfuse for both runtimes, which dreaming needs |
| Dreaming | Cron entry in Hermes, or keep the system cron. The trace source is Langfuse (both runtimes) | Script change: tag traces by runtime | M | Playbooks go to the shared core, not `~/.claude/CLAUDE.md` only |
| Ralph | `hermes cron` + PRD prompt + `pre_verify` gate | Built-in | M | `pre_verify` becomes the verification gate |
| Telegram gateway, session notify, stack alerts | Hermes messaging gateway + cron delivery | Built-in | S (to remove) | Retire after Phase 3 exit criteria |
| `healthcheck.sh`, `refinery-doctor.sh` | Same scripts, runtime-aware checks (`hermes doctor`, `mcp_servers` reachable, hooks consented) | Script | M | |
| Judge, gttp, pre-mortem, Superpowers | Skills | Same SKILL.md | S | Judge's subagent step maps to Hermes delegation |

### 5.2 Model access (see §6 for Claude)

```yaml
# ~/.hermes/config.yaml (illustrative; confirm keys with `hermes config` at install time)
model:
  provider: openrouter          # or anthropic (API key), ollama, custom, …
auxiliary:
  compression:                  # verified key (configuration.md); other aux tasks: vision, …
    provider: "auto"            # or a custom OpenAI-compatible base_url → local Ollama
    model: ""                   # empty = main model; set a small local model here
    base_url: null
fallback_providers: [...]       # verified top-level key; see fallback-providers.md
```

Local-model prerequisites, from Hermes docs and issue reports:

- A context window of 64K or more. Ollama's default of 4K breaks multi-step tool
  use.
- Models trained for tool calling.
- Expect unreliability under about 30B parameters.

Start local on **auxiliary** tasks, not the main loop.

### 5.3 Hook tool-name mapping

Claude Code and Hermes name tools differently. One mapping file in the core keeps
every hook script runtime-agnostic:

| Concept | Claude Code | Hermes (names found in `tools/*.py`) |
|---|---|---|
| Shell | `Bash` | `terminal` |
| Create file | `Write` | `write_file` |
| Edit file | `Edit` | `patch` |
| Skill write | n/a | `skill_manage` |

Both runtimes put the command at `tool_input.command` for shell. Verify the
write/patch argument keys before the edit-surface guard relies on them.

---

## 6. Running on the Claude subscription

### 6.1 Facts (Hermes docs at `f4d3e626`)

- Hermes's Anthropic OAuth path "routes as Claude Code". It **only works on Max
  with purchased extra-usage credits** and **never consumes the base Max
  allowance**. Pro cannot use it.
- Requests for a `claude -p`-backed provider were closed (#48320 as duplicate;
  #40014 and related as not planned).

### 6.2 Terms

- Anthropic's consumer terms update of 2026-02-19 says Free, Pro and Max OAuth
  tokens may not be used in third-party tools or the Agent SDK.
- Secondary reports describe enforcement in January and April, a reversal on
  2026-05-13, and a contributor claim that driving the official CLI is allowed.
  **None of the reversal claims were verified against Anthropic's own pages for
  this proposal.**
- Before Phase 4, read the current Consumer Terms and the Claude Code legal and
  compliance page yourself. If unclear, ask Anthropic support.

### 6.3 Options

| # | Approach | Uses base subscription? | Terms risk | Effort |
|---|---|---|---|---|
| 1 | **Keep Claude Code as its own runtime.** Hermes and Claude Code share the core. You choose per task | Yes | None, since this is how Claude Code is meant to be used | none (Phases 1–3 deliver it) |
| 2 | Hermes Anthropic OAuth | No, extra-usage credits only | Low (Hermes ships it) | S |
| 3 | Anthropic API key in Hermes | No, pay per token | None | S |
| 4 | **Claude Code runtime for Hermes**, modelled on the Codex app-server runtime. Hermes hands the whole turn to `claude -p --output-format stream-json`, and Claude Code runs the tools with the shared core | Yes | **Unclear.** It automates the official CLI, but on behalf of a third-party tool. Confirm first | L |
| 5 | Third-party OpenAI-compatible wrappers around Claude subscription credentials | Yes | **High.** This is the pattern the February terms target | — do not use |

**Recommendation:** Option 1 now, plus Option 3 or the cheap models for Hermes.
Revisit Option 4 only if (a) the terms clearly allow it and (b) Phase 3 shows Hermes
is where you want to live day to day.

Option 4's design, when it comes: a Hermes **model-provider/runtime plugin** that
mirrors `codex-app-server-runtime`. It spawns `claude -p` with `--output-format
stream-json --input-format stream-json` per session. It sends the composed Hermes
system prompt once (`--append-system-prompt`). It points Claude Code at the shared
core's MCP and hooks config, and projects Claude Code's events back into Hermes's
message shape so memory and skill review still see a normal transcript.

Your `telegram-gateway-poll.sh` already does a primitive version of this.

---

## 7. Phased plan with exit criteria

Each phase must pass the **standing test**: does it pay for itself on Right, then
Cheap, measurably?

### Phase 0 — Baseline (1–2 days)

- Build `bench/tasks/`: 20–30 real tasks taken from your own history (memweave or
  Langfuse). Mix code fixes, doc questions, data questions, "what did we decide"
  recall, and one unattended Ralph-style item. Each task needs a checkable answer
  or acceptance test.
- Record the Refinery on Claude Code for each task: correct (y/n), tokens or cost,
  wall time, interventions (count of times you had to step in).
- **Exit:** baseline table committed.

### Phase 1 — Extract the shared core, in this repo (3–5 days)

- `policy/ROUTING.md`: a model-agnostic routing policy of about 60 lines or fewer.
  Move the version-pinned patch notes out of the always-loaded `CLAUDE.md` into
  `docs/stack-notes.md`, loaded on demand through jdocmunch.
- `hooks/`: add `hooks/lib/toolmap.sh` (§5.3). Make each guard read
  `hook_event_name` and `tool_name` through it. Add tests that replay
  Claude-Code-shaped and Hermes-shaped payloads.
- `mcp/memweave/`: a stdio MCP server exposing `search(query,k)` and
  `append_note(text)`. Register it in Claude Code too.
- **Exit:** Claude Code behaves the same (Phase 0 tasks re-run without regression),
  and the `CLAUDE.md` token count drops.

### Phase 2 — Hermes side by side (3–5 days)

- Install Hermes under its own profile. Leave the Refinery untouched.
- Wire `mcp_servers`, `skills.external_dirs` → `global-skills/`, shell hooks with
  `fail_closed: true` on security gates, `skills.write_approval: true`,
  `memory.write_approval: true`, and the Langfuse plugin pointed at the existing
  instance.
- Build the `memweave` memory-provider plugin.
- Run Phase 0 tasks on Hermes with a Claude model (API key or OAuth extra usage)
  so the comparison isolates the **runtime**, not the model.
- **Exit:** Hermes is within about 5 points of the Refinery on correctness. All
  guardrail tests block in Hermes. Cost is reported.

### Phase 3 — Model routing and local rail (1–2 weeks, mostly measuring)

- Auxiliary tasks go to a local model (start with an 8B-class model). Then try a
  local main model on the easy third of the bench.
- Add one cheap cloud model via OpenRouter for comparison.
- Port Ralph to `hermes cron` with a `pre_verify` gate. Port notifications to the
  Hermes gateway.
- **Exit:** a cost-per-correct-answer table per model and hardware tier. That table
  is the evidence for the "cheapest hardware" goal. Decide which Refinery plumbing
  to retire.

### Phase 4 — Claude subscription runtime (optional, gated on §6.2)

- Only if the terms are confirmed and Hermes won Phase 3 on daily use.
- **Exit:** Hermes turns run on base Max quota with the shared core active inside
  Claude Code.

### Phase 5 — Retire duplicates

- Remove the Telegram gateway, notify, stack-alerts pollers and the Ralph cron
  wrapper from `install.sh` where Hermes replaced them. Update `README.md`,
  `PRODUCT.md` and the first-run gate.
- **Exit:** `healthcheck.sh` is green, the README has no drift, and the number of
  cron entries goes down.

### Later — the parts nobody ships

- **Distillation:** export high-scoring traces with Hermes's `batch_runner.py` /
  `trajectory_compressor.py` or from Langfuse, and fine-tune a small local model on
  your own work. Research warns that repeated self-distillation loops collapse, so
  do one round at a time, gated by the bench.
- **Tutor mode:** a `pre_llm_call` hook plus skill that, when enabled, makes the
  agent ask you to attempt first, quizzes you, and logs a skills ledger. Feeds the
  "teach me to be the best human" goal. Hermes's `USER.md` and Honcho user
  modeling are the natural home for the ledger.

---

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Hermes security surface: multiple CVEs reported in 2026, and self-written skills are a persistent injection vector | Medium | High | `write_approval` on, guard on, `fail_closed` security hooks, no LAN-exposed proxy or API server, pin Hermes versions, run `hermes update` deliberately |
| Hermes API churn breaks hooks or plugins | Medium | Medium | Shell hooks only, using the Claude-Code-compatible contract. No in-process plugins except memweave. A test suite replays payloads |
| Local models silently fail tool calls | High (<30B) | Medium | Local models start on auxiliary tasks only. The bench gates promotion. 64K+ context |
| Terms change around subscription use | Medium | High | Option 1 needs no terms bet. Option 4 only after a check |
| Two runtimes double the upkeep during the trial | High | Medium | Time-box Phases 2–3. Phase 5 exists to pay this back |
| Slimming `CLAUDE.md` loses hard-won rules | Medium | Medium | Move, don't delete. The rules stay searchable through jdocmunch |
| memweave provider prefetch leaks private vault content into prompts sent to cloud models | Low | High | Keep the `11 - Personal` / `12 - Archive` exclusions. Add a provider-side denylist |

---

## 9. Metrics (the standing test, made concrete)

Record each per runtime × model on the Phase 0 bench:

- **Correctness rate**: the gate, priority 1.
- **Cost per correct answer**: dollars plus tokens, and for local models amortised
  hardware plus electricity.
- **Interventions per task**: operator attention.
- **Upkeep**: cron entries, homegrown scripts, and hours per month spent on stack
  maintenance (from `HANDOFF.md` / git history).
- **Recall@5** on "what did we decide" questions (memweave vs Hermes
  `session_search` vs both).

---

## 10. Getting started in Claude Code

Concrete first steps, in order. Each block is a prompt you can paste into a Claude
Code session opened in this repo.

### 10.0 Before anything

```bash
cd "$STACK_ROOT"                              # /opt/proj/Uncle-J-s-Refinery on Linux
git switch -c feat/hermes-convergence
mkdir -p review && git clone --depth 1 https://github.com/NousResearch/hermes-agent review/hermes-agent
```

`review/` is already the convention for cloned reference repos (see `CHANGELOG.md`).
Make sure `review/` stays gitignored.

### 10.1 Prior art and goal check (5 min)

```
/prior-art-check hermes migration PORTING.md competitive analysis
/gttp Converge the Refinery onto Hermes per docs/proposals/2026-10-03-hermes-convergence.md.
      Challenge the plan before we start.
```

### 10.2 Index Hermes so the retrieval stack can answer questions about it

```
Index review/hermes-agent with jcodemunch (index_folder) and its website/docs with jdocmunch
(index_local, paths=[review/hermes-agent/website/docs]). Then answer from the index, not grep:
1. The exact pre_tool_call payload keys for terminal, write_file, patch and skill_manage.
2. The MemoryProvider abstract interface (method names + signatures).
3. The config keys for skills.write_approval, skills.external_dirs, mcp_servers, hooks,
   auxiliary.*, fallback providers.
Write the answers to docs/proposals/hermes-facts.md with file:line citations.
```

This turns §5.3's "verify against `hermes tools`" items into facts before any code
is written.

### 10.3 Phase 0 bench (plan mode)

Press Shift+Tab to enter plan mode, then:

```
Use the product-brief and pre-mortem skills. Build bench/tasks/: 25 tasks drawn from my
real history (search memweave and Langfuse for them). Each task gets: prompt, expected
answer or acceptance command, category. Add bench/run.sh that runs one task through a
given runtime and records correct/cost/time/interventions to bench/results/<runtime>.jsonl.
Show me the plan before writing files.
```

### 10.4 First code change: the tool-name map and hook payload tests (TDD)

```
Use the tdd skill. Create hooks/lib/toolmap.sh mapping Claude Code tool names
(Bash, Write, Edit) and Hermes names (terminal, write_file, patch) to canonical
names (shell, file_create, file_edit). Write tests first under tests/hooks/ that pipe
both payload shapes into hooks/discipline/push-guard.sh and assert exit 2 on
`git push origin main` for both. Then make push-guard.sh use the map. Run judge before commit.
```

Repeat for each guard. Each one is a small PR.

### 10.5 memweave MCP server

```
Use the tdd skill. Add mcp/memweave/server.py: a stdio MCP server exposing
search(query: str, k: int = 5) and append_note(text: str), calling the existing
scripts/memweave code (read-only store for search; append writes markdown into
~/.uncle-j-memory/memory/ only). Register it in mcp-clients/claude-code-mcp.json.
Verify with a real search. Keep the CLI working.
```

### 10.6 Slim the always-loaded policy

```
Use token-economy-prompt-authoring. Produce policy/ROUTING.md: the model-agnostic
routing rules from CLAUDE.md in ≤60 lines. Move every version-pinned "verified against
X.Y.Z" note into docs/stack-notes.md (indexed by jdocmunch). CLAUDE.md becomes
ROUTING.md + a pointer. Report before/after token counts. Do not delete any rule —
move it.
```

### 10.7 Hermes side-by-side install (Phase 2)

Run this outside Claude Code, in a terminal you control. It's an installer piped to
shell, so read it first:

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh -o /tmp/hermes-install.sh
less /tmp/hermes-install.sh && bash /tmp/hermes-install.sh
hermes setup        # choose a provider: an API key or OpenRouter for Phase 2, not subscription
```

Then back in Claude Code:

```
Write features/hermes/install.sh (idempotent, --uninstall supported, follows
lib/feature-helpers.sh conventions) that merges into ~/.hermes/config.yaml:
mcp_servers (all 6 + memweave-mcp), skills.external_dirs -> global-skills,
skills.write_approval: true, skills.guard_agent_created: true, memory.write_approval: true,
hooks (pre_tool_call guards with fail_closed: true), and the Langfuse plugin pointed at our
instance. Use hermes-facts.md for every key — no guessed keys. Add a healthcheck section.
```

### 10.8 Run the bench on both runtimes

```
Run bench/run.sh for every task on runtime=claude-code and runtime=hermes (same Claude
model). Produce bench/results/summary.md: correctness, cost per correct answer,
interventions, and the 5 biggest behavioural differences with trace links.
```

That summary is the decision point for Phases 3–5.

### 10.9 Working conventions for this effort

- Use one branch and one small PR per step. The repo's judge and per-task review
  cycle skills apply.
- Use git worktrees (`EnterWorktree` or `git worktree add`) to run Refinery and
  Hermes experiments in parallel without cross-contamination.
- Use Ralph for the mechanical parts. Write `PRD.md` items for §10.4 guard-by-guard
  ports with acceptance commands, then `./ralph-harness.sh`.
- Record decisions in memweave as you go (`post-audit-memory-capture`) so the next
  session doesn't re-litigate them.

---

## 11. Open questions for the owner

1. Which Claude plan are you on (Pro or Max)? This decides whether Option 2 exists
   at all.
2. What is the hardware budget for the local rail: current machine only, or a
   purchase (used 12 GB GPU, unified-memory mini PC)?
3. How much daily use should move to messaging platforms other than Telegram?
4. Is tutor mode a near-term want (Phase 3.5) or truly later?
5. Is `PORTING.md` to be archived (moved to `docs/history/`) once this is accepted?

---

## 12. Sources

Hermes, read from source at `f4d3e626`:

- `website/docs/user-guide/features/hooks.md` (shell hooks, Claude Code
  compatibility, exit 2, `fail_closed`)
- `website/docs/user-guide/features/skills.md` (`write_approval`,
  `guard_agent_created`, project-skill quarantine)
- `website/docs/user-guide/features/curator.md`
- `website/docs/user-guide/features/codex-app-server-runtime.md`
- `website/docs/user-guide/features/subscription-proxy.md` (Nous and xAI only;
  Anthropic Messages is out of scope)
- `website/docs/integrations/providers.md` (Claude Max extra-usage-only OAuth;
  local providers)
- `website/docs/developer-guide/memory-provider-plugin.md`
- `plugins/observability/langfuse/README.md`
- `hermes_cli/plugins.py` (`VALID_HOOKS`, `pre_tool_call` directives)

External:

- Hermes Agent repository: https://github.com/NousResearch/hermes-agent
- `claude -p` provider request (closed): https://github.com/NousResearch/hermes-agent/issues/48320
- OAuth bills extra usage (closed): https://github.com/NousResearch/hermes-agent/issues/40014
- Ollama tool-call hang: https://github.com/NousResearch/hermes-agent/issues/25629
- Anthropic subscription OAuth terms (Feb 2026), secondary report:
  https://winbuzzer.com/2026/02/19/anthropic-bans-claude-subscription-oauth-in-third-party-apps-xcxwbn/
- Hermes CVE summary (search snippet; the page was not readable from this environment):
  https://labs.cloudsecurityalliance.org/research/csa-research-note-hermes-agent-cves-20260504-csa-styled/
- Skill misevolution in self-improving agents: https://arxiv.org/pdf/2608.12851
- Agents that teach / skill atrophy: https://arxiv.org/html/2607.06101

Refinery, this repo: `README.md` (Mission), `PRODUCT.md`, `PORTING.md`,
`CHANGELOG.md` (2026-04-22, 2026-04-23, 2026-05-22),
`docs/superpowers/plans/2026-05-22-competitive-gap-closure.md`,
`docs/skill-frontmatter-standard.md`, `features/dreaming/README.md`.

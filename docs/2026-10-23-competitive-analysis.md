# Uncle J's Refinery — Competitive Analysis (2026-10-23)

Method: the `agent-harness-competitive-analysis` skill. Competitor facts come from each
project's README (fetched 2026-10-23) and the GitHub API (stars, dates, licence, same day).
Every competitor number is that project's own claim; none were verified by running them.
Refinery numbers come from this repo at `92a6fbf` (the jcodemunch index, `git ls-files`,
`just test`).

**TL;DR:** The big harnesses sell breadth (ECC's 71 agents and 311 skills, ruflo's 314 MCP
tools, Hermes's six chat platforms). Refinery is narrow and deep: one operator, one host
first, purpose-built retrieval per modality, and enforcement hooks that ship with tests.
The split is breadth you install versus controls you can verify.

## What Refinery actually is

- **Pattern:** an install-script stack around Claude Code. Global routing policy
  (`CLAUDE.md`), PreToolUse/Stop hooks, crons, and MCP servers. `just` is the front door.
- **Retrieval per modality:** jcodemunch (code), jdocmunch (docs), jdatamunch (CSV),
  duckdb (SQL), serena (LSP), context7 (library docs). There's an explicit absence contract:
  an empty result isn't treated as proof that something is absent.
- **Memory:** memweave, a local markdown corpus with embeddings, across projects. It holds
  transcripts plus an Obsidian vault mirror. The markdown is canonical, so the index can be
  rebuilt byte-for-byte.
- **Enforcement:** pre-mortem clearance tokens, push-guard, grep-guard, credential-guard,
  surface-write-guard and the commit doc gate. Each has a behaviour-matrix test in CI.
- **Local rail:** ask_local (Heretic on llama-server), with content-hash caching for batch
  jobs (`scripts/local_rail.py`).
- **Other subsystems:** Telegram gateway, repo scout, dreaming (Langfuse traces → playbooks),
  referee (Gemini second opinion), live_preview, partikus (CAD MCP).
- **Scale:** 463 tracked files. 106 Python and 90 bash files indexed, 2,234 symbols.
  73 global skills, 7 hook scripts, 7 MCP servers in the client template.
  1,025 commits since 2026-04-20; `just test` passes 1,951 tests.

## The competitor map

GitHub stars as of 2026-10-23:

| Project | Stars | Created | Licence |
|---|---|---|---|
| obra/superpowers | 304,162 | 2025-10-09 | MIT |
| affaan-m/ECC (Everything Claude Code) | 287,162 | 2026-01-18 | MIT |
| NousResearch/hermes-agent | 256,488 | 2025-07-22 | MIT |
| ruvnet/ruflo (formerly claude-flow) | 78,708 | 2025-06-02 | MIT |
| anthropics/claude-plugins-official | 44,077 | 2025-11-20 | Apache-2.0 |
| wshobson/agents | 41,607 | 2025-07-24 | MIT |
| SuperClaude-Org/SuperClaude_Framework | 23,910 | 2025-06-22 | MIT |

### 1. ECC — Most Direct Competitor

Same shape: a harness layer over Claude Code with agents, skills, hooks, memory and a
security scanner. Refinery imported six ECC agents in May and kept one (2026-10-23, see
`docs/RELIABILITY.md`).

| Dimension | ECC | Refinery |
|---|---|---|
| Breadth | 71 agents, 311 skills, 97 commands | 1 agent, 73 skills, ~22 `just` recipes |
| Harnesses | Claude Code stable; Codex, Qoder supported; ~13 more beta/experimental | Claude Code; Antigravity gets the stack (features/antigravity); skills portable via `~/.agents/skills` |
| Memory | Markdown "Memory Vault" + confidence-scored "instincts" | memweave: markdown corpus, embeddings, cross-project, rebuildable |
| Retrieval | No retrieval MCP by default (ships `chrome-devtools` only) | Six retrieval servers, one per modality, plus an absence contract |
| Security | AgentShield scans prompts, hooks, MCP config, secrets | Guards enforced as hooks, each with a CI behaviour matrix; jscrub invisible-Unicode gate |
| Install | `npx ecc-universal` (Node 18+), plugin, or install.sh | `./install.sh` / `just setup`, clean-container install gate |

**Where Refinery is stronger:** retrieval (ECC has no structural code index). Enforcement is
tested rather than declared. State is local and rebuildable.
**Where ECC is stronger:** breadth, multi-harness reach, one-command install, community.

### 2. obra/superpowers — Bigger Ecosystem (and a dependency)

A methodology of 15 auto-triggering skills (TDD, debugging, planning, review, worktrees)
across 16 harnesses. Refinery *uses* superpowers rather than competing with it. This
session's workflow skills are superpowers'.

| Dimension | superpowers | Refinery |
|---|---|---|
| Scope | Development methodology | Whole operating stack: retrieval, memory, guards, crons |
| Memory / retrieval | None described | memweave + six retrieval servers |
| Evals | drill eval harness (separate repo) | pytest behaviour matrices for guards; payoff audit |

**Where Refinery is stronger:** everything outside the dev loop.
**Where superpowers is stronger:** harness reach, plus a tested methodology that many
people use.

### 3. Hermes Agent — Closest in Spirit (different runtime)

A self-improving agent with its own runtime. It reaches the user wherever they are
(Telegram, Discord, Slack, WhatsApp, Signal, CLI), with built-in cron, 40+ tools, automatic
skill creation and FTS5 session search. Decision on record (2026-10-04): no Hermes. Uncle J
stays the runtime and adopts Hermes's best parts as MCP servers and scripts (ask_local,
memweave, the agy bridge).

| Dimension | Hermes | Refinery |
|---|---|---|
| Runtime | Own agent loop, any model provider | Claude Code (subscription), plus local model via ask_local |
| Skill creation | Automatic, refined during use, no approval step described | Drafts are approval-gated (Telegram `promote`), and a body scan runs before install |
| Messaging | 6+ platforms from one gateway | Telegram only, hardened (restricted agent, output redaction, rate limit) |
| Sandboxing | Six terminal backends (Docker, SSH, Modal…) | Restricted agent has no host access; host guards apply to sessions |

**Where Refinery is stronger:** structural retrieval. Skills are reviewed before they land.
It runs on a subscription instead of per-token billing.
**Where Hermes is stronger:** multi-platform reach, model freedom, a self-contained runtime,
sandbox backends.

### 4. ruflo (claude-flow) — Bigger Ecosystem (swarm orchestration)

Swarm orchestration for Claude Code and Codex: 100+ agents, 314 MCP tools, AgentDB with
HNSW memory, federation across machines, Ollama routing via a plugin.

**Where Refinery is stronger:** a small, auditable surface, where ruflo claims 314 tools.
Every Refinery control has a test, and the stack runs offline-capable on one host.
**Where ruflo is stronger:** multi-agent topology, cross-machine federation (Refinery syncs
its three hosts by hand), and sheer tool count.

### 5. Official plugins directory and agent marketplaces — Official Platform

`anthropics/claude-plugins-official` (44k stars), `wshobson/agents` (multi-harness
marketplace, 41.6k) and SuperClaude (personas and commands, 23.9k) are distribution channels
for parts, not stacks. Refinery consumes from them (superpowers, ralph-wiggum) and could
publish its own pieces there. It doesn't today.

## Where Refinery has no real competition

1. **Retrieval per modality with an absence contract.** No competitor ships a code index, a
   doc index and a data index that report `absent` vs `degraded`. "Found nothing" is never
   read as "doesn't exist" (CLAUDE.md, absence contract).
2. **Tested enforcement, not declared policy.** push-guard, grep-guard, surface-write-guard,
   credential-guard and the pre-mortem token each have a behaviour matrix in CI, with BLOCK
   cases first. ECC's AgentShield scans config, while Refinery's guards block actions at the
   moment they're attempted.
3. **Local-canonical memory.** memweave's markdown store is the source of truth. A crash
   recovery test rebuilt the index byte-for-byte from the .md files. Hermes and ECC keep
   memory too, but neither claims a rebuildable source of truth.
4. **Decisions that cite evidence.** Upstream claims are checked against the installed
   package source before routing policy changes (`index_dependency`, the "verify CLAUDE.md
   against installed code" rule). No competitor describes anything like it.
5. **Subscription-billed automation with a local rail.** Crons call `claude -p` with API keys
   stripped (2026-10-23), and bulk work goes to a local model through a cached rail. That
   makes unattended work close to zero marginal cost.

## Gaps worth acting on

- **Install friction and reach.** Competitors install in one command into many harnesses.
  A plugin packaging of the guards and skills would reach the marketplaces.
- **Multi-host.** Refinery's three hosts sync by hand, while ruflo federates. The ROADMAP's
  "one always-on host as the brain" item is the planned answer.
- **Breadth of chat surfaces.** Telegram only, compared with Hermes's six. This is low
  priority: the channel is for approvals, not chat.

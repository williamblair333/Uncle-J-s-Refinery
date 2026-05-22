# ECC Import Proposal

**Source:** `_reviewed/ECC/` — Everything Claude Code v2.0.0-rc.1  
**Analysis date:** 2026-05-22  
**Status:** Tier 1 implemented 2026-05-22 — 6 agents in `global-agents/`, symlinked to `~/.claude/agents/`  
**Prior art:** competitive analysis saved to MemPalace (`uncle_j_s_refinery / competitive-intel`)

---

## What ECC Has That We Don't

| ECC component | Our equivalent | Gap |
|---|---|---|
| 60 specialist agents | 0 installed | **Real gap — highest ROI** |
| Context profiles (dev/review/research) | None | Worthwhile |
| Language-specific rules (12 ecosystems) | Embedded in CLAUDE.md | Low priority |
| ecc2 Rust TUI daemon | healthcheck.sh + Langfuse | Not needed |
| 232 generic skills | 29 custom skills | Not a gap — ours are better |
| npm distribution | install.sh | Not a gap — different target |

---

## Tier 1 — Import Now (highest ROI, no overlap)

### Agent library — core 7

We have 25 hooks, 6 MCP servers, a self-improvement loop, and Langfuse. What we're missing is **specialist subagent delegation**. These agents slot directly into our existing hook and skill system.

| Agent | File | Why |
|---|---|---|
| `planner` | `agents/planner.md` | Breaks complex tasks into implementation phases before touching code. Maps to our `superpowers:writing-plans` but is a proper subagent. Model: Opus. |
| `code-reviewer` | `agents/code-reviewer.md` | Code quality + security review post-edit. Complements our `judge` skill (which gates writes) — this runs after. Model: Sonnet. |
| `security-reviewer` | `agents/security-reviewer.md` | OWASP/injection/secret/auth specialist. Our guardrails block at the hook level; this catches logic-level vulnerabilities in the code itself. |
| `architect` | `agents/architect.md` | System design and scalability decisions. Opus-backed. Pairs with `superpowers:brainstorming`. |
| `tdd-guide` | `agents/tdd-guide.md` | RED → GREEN → IMPROVE enforcement. Our `superpowers:test-driven-development` skill covers the pattern; this is a dedicated subagent. |
| `performance-optimizer` | `agents/performance-optimizer.md` | Pairs well with jCodeMunch's `get_hotspots` + `get_symbol_complexity`. |
| `silent-failure-hunter` | `agents/silent-failure-hunter.md` | Finds code that swallows errors silently — a real blind spot, nothing in our stack catches this. |

**How to import:**
```bash
mkdir -p ~/.claude/agents
for agent in planner code-reviewer security-reviewer architect tdd-guide performance-optimizer silent-failure-hunter; do
    cp _review/ECC/agents/${agent}.md ~/.claude/agents/
done
```

Then verify they appear with `claude agents list` (or check `~/.claude/agents/`).

---

## Tier 2 — Consider (smaller ROI, some adaptation needed)

### Context profiles

ECC ships three CLAUDE.md-style snippet files that swap in a focused behavior set for a given mode. Lightweight and worth having.

| Context | What it does |
|---|---|
| `dev.md` | Code-first, ship-fast, atomic commits mode |
| `review.md` | Read-before-commenting, severity-ranked findings, checklist-driven |
| `research.md` | Investigation and synthesis mode |

**How to import:** Copy to `~/.claude/contexts/` and invoke with `claude --context dev` (or symlink as slash commands if the CLI supports it). Needs testing against our CLAUDE.md to ensure no policy conflicts.

### `python-reviewer` agent

We're Python-dominant (168 of 267 files). ECC's `agents/python-reviewer.md` covers idioms, type hints, and performance patterns. Worth adding alongside `code-reviewer` for Python-specific passes.

---

## Tier 3 — Skip (we have better or different enough)

| ECC component | Why to skip |
|---|---|
| 232 generic skills | Our 29 are project-specific and tuned to our actual workflows. Generic skill breadth doesn't help a one-operator system. |
| hooks/hooks.json system | Our 25-hook system with jcodemunch integration is far more sophisticated. Their run-with-flags wrapper solves a problem we don't have. |
| Rules system (110 files) | Embedded in our CLAUDE.md routing policy. Adding separate rule files adds maintenance overhead with no clear benefit. |
| ecc2 Rust daemon | We have Langfuse + healthcheck.sh. Their TUI is alpha. Not worth porting. |
| npm distribution | We're not distributing. |
| `chief-of-staff` agent | Email/Slack/LINE triage. Not relevant to this harness. |

---

## Implementation order

1. **Import core 7 agents** — one `cp` command, zero risk, immediate benefit
2. **Test context profiles** — copy to `~/.claude/contexts/`, try `dev.md` in a session, check for CLAUDE.md conflicts
3. **Add `python-reviewer`** — after agents are working, add the Python specialist

---

## Cross-check against our existing capabilities

Before importing any ECC skill/agent, verify it doesn't duplicate something we already have better:

| ECC item | Our equivalent | Verdict |
|---|---|---|
| `prior-art-check` skill | `global-skills/prior-art-check/` (MemPalace-backed) | Skip — ours is better (theirs is generic; ours hits MemPalace) |
| `orchestrator` skill | `global-skills/orchestrator/` | Skip |
| `judge` skill | `global-skills/judge/` (jcodemunch-backed) | Skip — ours adds blast radius + PR risk |
| `planner` agent | None | **Import** |
| `code-reviewer` agent | `judge` skill (different — skill gates writes; agent reviews after) | **Import both** |

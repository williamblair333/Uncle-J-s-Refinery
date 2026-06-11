# Refinery Improvement Program — Design

*2026-06-11. Approved direction from mission-definition session. Evaluates everything
against the README Mission: Right > Cheap-in-total > Inventive > Local, standing test:
every component must pay for itself, measurably — or be removed.*

## Cross-cutting principles (apply to every phase)

**P1 — Deterministic-first.** Programs do as much of the work as possible. Mechanical
steps (hashing, counting, diffing, filtering, thresholding, format conversion,
scheduling) are scripts. LLM calls are reserved for genuine judgment — synthesis,
fuzzy classification — at the smallest sufficient model, with outputs validated by
deterministic checks. Precedent in-repo: smart-review's rules floor runs before its
classifier.

**P2 — Local-canonical, API-optional.** Learning/memory artifacts (playbooks,
patterns, mined sessions) live in a local, model-agnostic store (MemPalace or
successor; SQLite + markdown). Local models and Claude both read/write it. Claude
Code's native memory and Anthropic's native Dreaming act as distilled mirrors,
never the only copy. Batch pipelines run local-first with API fallback.

## Phase 1 — Pay-for-itself audit (the standing test's first run)

Goal: a per-component scorecard → keep / fix / delete list. Re-ranks all later work.

- **Collectors are pure scripts** (P1):
  - Always-on token cost per component: CLAUDE.md section sizes, tool-description
    overhead at current tier, hook/reminder injection — from Langfuse exports and
    static byte counts.
  - Maintenance burden: commits + sessions per component from git log / HANDOFF /
    CHANGELOG scan (pattern-match component names; count and date-bucket).
  - Benefit counters: jcodemunch `get_session_stats` savings, `hook-blocks.log`
    guard catches, MemPalace prior-art hit rate (search calls that informed a turn).
- **LLM involvement**: one synthesis pass over the collected numbers. Nothing else.
- **Output**: `state/payoff-scorecard.md` + ROADMAP deletions/fixes.
- Live evidence already in hand: MemPalace search failed twice on 2026-06-11
  ("ef or M is too small", then "cand error" post-reconnect) while its repair
  apparatus consumes a double-digit share of recent sessions.

## Phase 2 — Accuracy instrumentation (priority #1 currently has no metric)

- **Memory recall benchmark**: ground-truth probe set (question → drawer that must
  surface). Script harness, weekly cron, trend in weekly stats report. Establishes
  ChromaDB baseline; only existing number is turbovecdb's recall@10=0.408 (candidate
  backend, no incumbent baseline).
- **Correction ledger**: hook-based — when the user corrects a wrong answer, log a
  structured event. Right-answer rate becomes a trend line. Deterministic capture;
  no LLM in the loop.
- **Citation audit** (long-open): stop-hook script greps session JSONL for URLs,
  cross-checks against WebFetch/gh tool uses in the same session; verified/unverified
  flag flows into the dreaming pipeline. Structurally closes the fabrication path.
- **Backend selection** follows from the benchmark — user mandate 2026-06-11:
  nothing is sacred, pick whatever is best. Candidates, judged on recall ≥
  ChromaDB baseline + zero-maintenance operation:
  1. **turbovecdb** — 49× faster p50, recall@10=0.408 must be tuned up (ef);
     eval rig already live (PR #23)
  2. **sqlite-vec** — boring single-file storage, no service, no private APIs
  3. **roll-our-own** — SQLite FTS5 + vec hybrid; only if both above fail the
     benchmark; keep it deliberately dumb (P1)
  4. **keep ChromaDB** — only if it wins outright
  The **MemPalace application layer** (wings/drawers/mining/diary UX) is evaluated
  separately from its storage: storage can swap underneath it; the layer itself is
  retired only if the Phase 1 audit shows it doesn't pay. Whatever wins, the ChromaDB
  corruption-repair apparatus (repair crons, force-flush private-API hack, ~12 repair
  skills) is deleted with the swap — largest single Cheap-in-total win available.

## Phase 3 — Local rail (priority #4, least developed)

- **Ollama endpoint** (OpenAI-compatible, localhost:11434). Model selected by a
  hardware-detect script at install: Qwen3-Coder 30B class (24GB), Devstral Small
  24B (16GB), Qwen3 8B (8GB). Registered in healthcheck.
- **Migrate batch pipelines local-first** (API fallback on failure):
  1. MemPalace mine compression (with content-hash caching — pure script skip-list,
     ~50 lines, P1)
  2. Dream synthesis (`dream.sh` synthesizer call)
  3. `jcodemunch_guide` compression pass (already-planned ROADMAP item — the
     compress-and-benchmark loop runs on the local model)
- **Dual-track dreaming** (P2): MemPalace stays canonical; a distilled mirror is
  written to Claude Code's native memory directory so native recall benefits too.
  Native Dreaming (managed-agents beta) evaluated as consumer, not replacement.
- **Pattern-importance scoring**: frequency × recency × consequence-severity —
  pure arithmetic in drawer metadata. Script, no LLM (P1).

## Phase 4 — Subtraction & absorption

- Execute Phase 1's delete list.
- **CLAUDE.md de-dup**: project file becomes a stub pointing at global (~4k
  tokens/session in this repo). Trivial, immediate.
- **Absorption check**: extend `post-upgrade-mcp-integration` — script diffs the
  Claude Code changelog against a manifest of harness layers; flags native features
  that obsolete custom ones (e.g., native Dreaming, compaction API, deferred tool
  loading). LLM summarizes the diff only.

## Sequencing

Phase 1 first (one session; re-ranks the rest with evidence). Phase 2 benchmark
before any backend swap. Phase 3 independent of 1–2, can interleave. Phase 4
deletions gated on Phase 1 output; de-dup and absorption check anytime.

## Out of scope

@TAG/EVT notation for skills (rejected in NEQ analysis), PostToolUse-triggered
compression (wrong hook — rejected), replacing API Claude for interactive sessions
(local models serve batch pipelines only, for now).

## Risks

- Local model quality on synthesis tasks — mitigated by P1 validation checks and
  API fallback; benchmark before/after on dream output quality.
- Benchmark probe set bias — keep probes versioned in-repo; grow from real misses.
- Audit under-counts diffuse benefits (e.g., guardrails' deterrence) — scorecard
  notes confidence per row; deletion requires user sign-off, never automatic.

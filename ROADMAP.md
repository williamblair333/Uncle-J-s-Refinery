# ROADMAP — Uncle J's Refinery

Living roadmap. Updated at each session end when items complete or new ones surface.
Completed items age out after ~4 weeks.

---

## In Progress

- _(nothing in flight)_

## Recently completed (2026-06-24 — uv-sync recovery + install.sh memweave-venv gap closed)

- **Recovered a machine from a stray plain `uv sync`** (no `--inexact`): it wiped `.venv`
  site-packages — langfuse, the §2b pysqlite3 swap, and the retired mempalace/chromadb deps.
  Restored langfuse + the swap, built `.venv-memweave` + memory index, registered the
  `uncle-j-memweave-sync` cron, installed the `jcodemunch-watch` unit. `HEALTHCHECK: ok`.
- **`install.sh` §2c — provisions `.venv-memweave`** (PR #83): closes the gap where the
  installer never created the 3.12 memweave venv, so memory sync + the Stop hook died on any
  machine that hadn't built it by hand.
- **Mempalace fully retired:** removed the 6 stale `uncle-j-mempalace-*` crons (their scripts
  were already deleted) + untracked `mempalace.yaml`/`entities.json`. (Repo was already decommissioned.)
- Committed the jcode/jdata/jdoc `uv.lock` bump + rebuilt vendored pysqlite3 wheel.

## Recently completed (2026-06-16 — healthcheck loop fixed + pin-canary direct Python)

- **4 healthcheck bugs fixed:** MCP not-Connected hint no longer triggers install.sh; Langfuse
  checks gate on `LANGFUSE_PUBLIC_KEY` so unconfigured machines skip silently; 3 feature-specific
  crons removed from mandatory EXPECTED array; pin-canary hint restored to interactive `run:` form.
- **`scripts/pin-canary.sh` rewritten:** now calls `capture_canary()` directly via `.venv/bin/python`
  from `jcodemunch_mcp.retrieval.embed_drift` — no `claude` binary, no MCP session required.
  Removed the `CLAUDE_CODE_SESSION` guard and `claude -p` approach entirely.

## Recently completed (2026-06-15/16 — git pull self-healing)

- **PR #77 merged:** `install-reliability.sh` prunes stale `~/.claude/skills/` symlinks on re-run;
  `scripts/post-merge-hook.sh` auto-runs `install-reliability.sh` when `global-skills/` or the
  installer changes. `git pull` is now the one command — no manual re-run needed for skill changes.

## Recently completed (2026-06-14 — cron silent failures + healthcheck runtime probes)

- **3 silent cron failures fixed:** `dream.sh` PATH export (dreaming broken since Jun 10 — cron
  couldn't find `claude`); `state/dreaming.env` unquoted cron schedule (bash parsed `2 * * *` as
  a command on every source); `auto-maintain.sh:294` `${#SKILL_NAMES[@]:-0}` invalid bash
  (bad substitution on every run). Healthcheck added `check_dreaming_runtime` (last-run freshness
  >36h = FAIL, surfaces `!!` log clues) + `check_auto_maintain_runtime` (shell error pattern scan).

## Recently completed (2026-06-14 — follow-up sweep + Telegram incident)

- **Telegram red-team depth findings closed (PR #73):** whole-file injection scan on `promote`
  (frontmatter included), `assert_skill_target_safe` removes the destructive `rmtree`, output
  redaction gains relative-`.env` + spaced-`sk-ant` patterns (+ left-boundary fix on the existing key rule).
- **getUpdates single-consumer — 22-day offset-freeze incident (PR #74):** two cron pollers consumed
  one bot token; made the gateway the sole consumer (approve/skip relayed via
  `state/stack-alerts-callback.json`), + F4 log byte-sanitize, F5 datetime tz-aware, per-poll
  observability line. **Freeze resolved live** by repointing the corrupt offset into the real id range.
- **Drain helper hardened + `--catch-up` (PR #76):** removed the negative-offset footgun (it
  confirmed/ate a live test DM); dry-run is now genuinely read-only; `--catch-up` repoints to the
  oldest unconfirmed id so queued messages are answered, not skipped.
- **healthcheck probes (PR #75):** `jcodemunch-watch` daemon liveness (warn-not-fail under cron) +
  memweave index freshness (<48h).

## Recently completed (2026-06-13/14 — security & retrieval hardening)

- **memweave corpus de-noised (PR #71):** skill invocations inject the skill's full body as a
  user-role turn (`Base directory for this skill:`), which the exporter indexed as searchable
  prose — flooding prior-art search with stale (often superseded) skill copies. `iter_turns` now
  drops these; `export_project` made authoritative (deletes a stale `.md` when a session falls
  below `min_chars` after filtering). Corpus rebuilt from scratch (577 indexed / 7746 chunks);
  transcripts untouched. Also committed the `jdocmunch-mcp` 1.70.2→1.71.0 autofix `uv.lock` bump.
- **Telegram restricted-agent lockdown (PR #68):** red-team found a CRITICAL — the restricted
  (untrusted) agent ran `claude --dangerously-skip-permissions` with no tool restriction, so a
  prompt injection could read `.env`/host files and exfiltrate out-of-band. Fixed via tested
  `build_claude_argv()` (no skip-perms / `--strict-mcp-config` / `--disallowedTools`); `/work`
  agent unchanged.
- **jcode watch daemon + grep-guard hardening (PR #69):** activated the `jcodemunch-watch` user
  service (real-time index freshness across all 9 repos); rewrote `grep-guard.sh` to route ALL
  source-code reads (not just `grep -r`) to jcodemunch via per-segment dispatch.
- **understand-anything plugin enabled in project settings (PR #67).**

## Recently completed (memweave migration — fully closed 2026-06-13)

- **LIVE residue scrub (PR #63):** repointed 18 global skills + feature docs + PORTING.md + flowchart
  + GEMINI.md off mempalace → memweave; deleted dead recall-bench + `CLAUDE.md.merged` + `entities.json`.
- **jmunch stack upgraded to HEAD (PR #64):** jcode 1.108.55 / jdata 1.13.1 / jdoc 1.70.2; cleared
  `stack-not-at-head`. (Restart Claude Code to load the new MCP servers; run
  `post-upgrade-mcp-integration` next session.)
- **Audit-sink repoint (PR #57) + `post-audit-mempalace-capture`→`post-audit-memory-capture` (PR #62)**
  + global `~/.claude/` edits applied at the keyboard. The migration (PRs #45–#64) is complete in-repo
  and in global config; mempalace fully decommissioned.
- *(obsolete — mempalace gone)* ~~Upstream MemPalace PR #1607~~ / ~~turbovecdb parallel eval~~.

**Only genuinely-remaining deferred item:** purge the staged trash dirs (2.4 G + 55 G, irreversible —
Bill's call). See HANDOFF + `project_memweave-migration-done`.

## Planned

**Improvement Program** (spec: `docs/superpowers/specs/2026-06-11-refinery-improvement-program-design.md` — phases in order; principles: deterministic-first, local-canonical):

- **Phase 2 — Accuracy instrumentation → memweave migration** ✅ **DONE 2026-06-13** (see Completed). Backend decision (MemPalace eliminated → memweave) resolved 2026-06-12; memweave built (PRs #45–#48) and the full migration + mempalace decommission shipped (PRs #50–#55).
- **Phase 3 — Local rail** — Ollama endpoint + hardware-detect model select (Qwen3-Coder 30B / Devstral 24B / Qwen3 8B tiers); batch pipelines local-first (mine compression w/ content-hash caching, dream synthesis, guide compression); dreaming now promotes into the memweave store; pattern-importance scoring as pure script
- **Phase 4 — Subtraction & absorption** — signed-off deletions (Bill, 2026-06-11): ~~D1 stale palace copies (55GB)~~ executed 2026-06-11; ~~**D2** ChromaDB repair apparatus~~ **DONE 2026-06-13** (mempalace fully decommissioned, PRs #50–#55); **D3** ralph — only if Phase 2 usage counter confirms idle. Plus: CLAUDE.md de-dup (project stub, ~4k tokens/session); absorption check added to `post-upgrade-mcp-integration` (script-diff Claude Code changelog vs harness-layer manifest)

- **Compressed `jcodemunch_guide` return value** — offline compress `_generate_claude_md_snippet()` output via cheap model (Phase 3 local rail candidate); benchmark 20 representative routing queries before/after; ~4,600–5,100 tokens/session savings at full tier; upstream contribution to jcodemunch

- **ralph-harness env-strip (after 2026-06-15)** — strip `ANTHROPIC_API_KEY` + `ANTHROPIC_AUTH_TOKEN` from subprocess env in `ralph-harness.sh` and Telegram gateway; enables Agent SDK credit billing ($0 actual cost within monthly credit); do NOT apply before June 15

- **Telegram chat history persistence** — skill exists (`telegram-chat-history-persistence`)
  but implementation not yet started; would allow querying past bot conversations

- **Agent harness competitive analysis** — skill exists; full analysis not yet run

- **ECC specialist agents** — 6 agents imported; evaluate and integrate into
  active workflows

- **grep-guard false positive: `~/.uncle-j-memory/` reads** — `grep-guard.sh` incorrectly blocked
  3 reads of `~/.uncle-j-memory/memory/premortem-audit.md` (outside the repo; not source). The
  guard should allow reads to paths outside `$PROJ_ROOT`. Narrow the pattern before the next
  session that needs `pre-mortem` prior-art checks; the 3 retries wasted time.

- **Expand discipline hook surface list** — after 1 week of `hook-blocks.log` data, review BLOCKED patterns and expand `edit-surface-guard.sh` surface list if coverage gaps appear; narrow if false positives are high

- **Telegram gateway — remaining red-team findings** (from `review/telegram-gateway-redteam.md`, which is gitignored — tracked here so they aren't lost): (a) skill-frontmatter prompt injection — `scan_skill_body` scans body only; (b) destructive `promote` `rmtree` on skill-name collision; (c) output-redaction denylist gaps (spaced/prose keys, relative paths); (d) bot token in curl URL → `/proc` disclosure. The CRITICAL (restricted-agent host access) is already fixed in PR #68.

---

## Completed (recent)

| Date | Item |
|------|------|
| 2026-06-13 | **pysqlite3 3.51.3 wheel vendored + "duckdb" healthcheck bug root-caused** (PR #65). The recurring `mcp-servers-down(duckdb)` fail was a checkmark codepoint bug (`✓` U+2713 grep vs `✔` U+2714 output) matching zero servers → headlined `missing[0]`=duckdb; fixed to `[✓✔]`. Vendored the pysqlite3-3.51.3 wheel (`scripts/build-vendored-pysqlite3.sh` → `vendor/wheels/`), marker-conditional pin in `pyproject.toml` (PyPI fallback off-platform), `check_sqlite_version` healthcheck assert. Ends the `uv sync` clobber dance permanently. |
| 2026-06-13 | **memweave migration complete — mempalace decommissioned** (PRs #50–#55). 2b-2 freshness cron + Stop-hook; 3b project CLAUDE.md routing → `mw_search.py`; 4a cross-project corpus (`--all-projects`); 4b decommission (scripts/crons/MCP/probes removed, palace staged not deleted, dreaming + 3 global skills repointed); 4c in-repo residue (dead `check_mempalace`, 6 obsolete repair skills, RELIABILITY scrub); 4d removed mempalace/chromadb deps from pyproject/uv.lock; 4e docs sync (README/STACK/ROADMAP + mcp-clients templates). Memory is now offline cross-project memweave (`~/.uncle-j-memory`). Deferred: global `~/.claude/` edits (harness-denied), control-invariant audit-sink repoint, trash purge. |
| 2026-06-11 | Improvement Program Phase 1 — pay-for-itself audit (PR #38): deterministic collectors + scorecard + judgment. KEEP: jmunch-retrieval (5,300:1 payoff), guardrails (315 blocks), langfuse, telegram. FIX: routing-policy (9k tok/session), mempalace storage (0.32 maint share), reliability, skills (prune), dreaming + ralph (instrument). D1–D3 deletions signed off. |
| 2026-06-06 | `dcup` Docker port registry — SQLite registry, flock mutual exclusion, live-reality preflight, sweeper service, PreToolUse hook; 26 projects registered |
| 2026-06-06 | `adversarial-review` skill + workflow — MAD framework (Paranoid/Archaeologist/Pedant/Cynic), 2 debate rounds, judge synthesis |
| 2026-06-06 | `smart-review` skill — rules floor + shadow classifier + drift audit; replaces manual effort-level selection |
| 2026-06-10 | F-04 closed — `healthcheck.sh` `check_mempalace()` now runs both `PRAGMA quick_check` (B-tree) and FTS5 `integrity-check` (inverted-index data layer) as complementary probes |
| 2026-06-10 | ARCHAEOLOGIST-R2-1 closed — post-upgrade SKILL.md step 8 clears `state/post-upgrade-needed`; `session-start-autofix.sh` section 0 warns if flag exists from a prior session |
| 2026-06-10 | PEDANT-R2-1 closed — `auto-maintain.sh` Telegram notification now includes per-package commit range (e.g., `jcodemunch-mcp (abc1234→def5678)`) |
| 2026-06-10 | jragmunch-cli evaluation — verdict: adopt env-strip billing pattern in ralph + Telegram gateway after 2026-06-15 (Agent SDK credit launch); skip review/sweep/changelog verbs (redundant with existing stack) |
| 2026-06-10 | CI test job for `session-end-check.sh` — `test-session-end-check` job added to `ci.yml`; 10 tests (pre-commit + stop-hook modes), 0 API calls, runs on ubuntu-latest |
| 2026-06-10 | Stop-hook session mining — `.claude/settings.json` Stop hook now routes through `scripts/mempalace-mine-convos.sh`; adds HNSW pre/post guard, flock dedup, `--wing conversations` consistency with cron; eliminates dirty-context window |
| 2026-06-10 | post-upgrade-mcp-integration jdatamunch 1.13.0 / jdocmunch 1.69.1 / mempalace 3.4.0 — 19 new tools routed in both CLAUDE.md files; stale `state/post-upgrade-needed` flag cleared |
| 2026-06-10 | post-upgrade-mcp-integration v1.108.50 — `get_session_stats`, `analyze_perf`, `tune_weights`, `test_summarizer` added to jcodemunch Session & tier config in both CLAUDE.md files |
| 2026-06-10 | MCP-Universe skill regression gate — `tests/test_skills.py` (576 static tests, 0 API calls); CI job 4; 6 malformed SKILL.md files fixed (missing `---`, invalid YAML); PR #36 |
| 2026-06-10 | Skill frontmatter standard — hermes-inspired YAML spec (platforms, category, tags, prerequisites, related_skills) written to `state/skill-frontmatter-standard.md`; pilot migration of pre-mortem, smart-review, session-end-checklist, prior-art-check; PR #35 |
| 2026-06-10 | jOutputMunch adoption — `## Output Token Economy` section added to both CLAUDE.md files; adversarial-review ran (2 HIGH + 6 MEDIUM fixed); SHA-pinned citation, correct null-strip predicate, success:false clause restored; PR #33 |
| 2026-06-10 | F-03 closed — bypass instruction removed from smart-review SKILL.md Step 6 and hook stderr; hook now says "Run /smart-review" |
| 2026-06-10 | F-05 closed — `gh pr *` hook split into `gh pr create *` + `gh pr merge *`; `gh pr list/view/status` no longer blocked |
| 2026-06-10 | CYNIC-R2-4 closed — flock guard + explicit exec error handling in `scripts/jcodemunch-reindex.sh` |
| 2026-06-10 | duckdb healthcheck false-positive fixed — 3s retry for uvx cold-start in `healthcheck.sh` |
| 2026-06-06 | Smart-review auto-invocation gates — PreToolUse hooks block `git push` / `gh pr create` without review clearance marker |
| 2026-06-05 | MemPalace HNSW empty-index root cause fixed — `repair --from-sqlite` leaves 0-byte `link_lists.bin` for small collections (< 50K items); fixed by post-repair force-flush step, writer-check MCP exclusion, healthcheck per-collection sync + 0-byte detection + auto-repair; upstream bug report + PR draft written |
| 2026-06-05 | design memory system — 5 MemPalace entries (pre-mortem invariants, enforcement hook attack vectors, dreaming pipeline, Telegram gateway, HNSW/FTS5+healthcheck); `post-audit-mempalace-capture` skill committed; pre-mortem step 11 + session-end-checklist Step 6b wired |
| 2026-06-05 | pre-mortem skill hardened — 3-cycle red/blue-team; 27 patches; 2 CRITICALs + 7 HIGHs closed; MEDIUM bundle, WarGames cap, fail-closed audit, cross-session memory |
| 2026-06-05 | turbovecdb security PR #2 merged — all findings fixed, 7 new tests, 46/46 passing |
| 2026-06-04 | turbovecdb security review — 1 HIGH + 1 MEDIUM + 2 LOWs found and fixed; PR #2 submitted to kostadis/turbovecdb; 7 new tests; scale test (290K drawers) pending |
| 2026-06-03 | MemPalace community knowledge share — two GitHub Discussions published: journey/war-story post (#1685) + HNSW silent corruption technical reference (#1686); covers Rust binding bug, dict pickle, FTS5 false-ok, SQLite mismatch, nightly cron destroy |
| 2026-06-03 | Dreaming CLAUDE.md injection path closed (palace path + pattern-promotion mitigated, not closed) — URL hold-filter in `dream.sh` quarantines URL-bearing playbooks to `state/dream-pending-review/`; cascade guard preserves CLAUDE.md if all playbooks held; `dream-synthesizer` SKILL.md anti-promotion rule for citation behaviors; Stop-hook citation audit still needed to structurally close pattern-promotion |
| 2026-06-03 | Dict-pickle root cause closed — verified `_persist()` is sole `pickle.dump` in chromadb; dict can't recur via any normal op; Step 2b (dead WAL commit, failed every run) removed from repair script; Step 2c comment corrected |
| 2026-06-03 | MemPalace dict-format pickle detection hardened — `healthcheck.sh` now probes pickle type (BAD:/ERR: discrimination, traceback-safe); `mempalace-repair-now.sh` Step 2c auto-migrates dict→SimpleNamespace after every repair; three code-review bugs fixed |
| 2026-06-03 | SQLite WAL data race bug fixed — upgraded to 3.51.3 via pysqlite3 source build; `.pth` patch covers all venv processes; install.sh step 2b auto-rebuilds on fresh machines; scan-commit.sh lockfile exemption fixed |
| 2026-06-03 | FTS5 corruption root cause eliminated — disabled `fts5-guard.sh` (concurrent B-tree corruptor), fixed `session-start-autofix.sh` to use venv Python + PRAGMA quick_check + flock, fixed healthcheck false-ok (was using FTS5 integrity-check), fixed `install_cron()` prefix matching, deduplicated 6 crontab entries; HEALTHCHECK: ok |
| 2026-05-28 | Review-queue triage workflow — `review-queue-triage` skill in regular session rhythm; `_review/` cleared |
| 2026-05-28 | Telegram multi-agent routing — `/work <msg>` dispatches to project-context Claude (CLAUDE.md loaded); default stays restricted; `config/telegram-agents.toml` config; hardcoded fallback on missing/malformed TOML; PR #20 |
| 2026-05-28 | MemPalace HNSW nightly destruction fixed — three-bug root cause: missing `--skip-if-healthy`, WAL never committed to HNSW, post-repair check SQLite-only; PR #19 |
| 2026-05-27 | `install-reliability.sh` plugin auto-install — superpowers + ralph-wiggum at user scope; `skill-link.sh` Stop hook no longer unlinks global-skills |
| 2026-05-27 | FTS5 guard + repair/mine coordination + skill-link blocking fix; `features/mempalace/install.sh` cron coordination; PR #14 |
| 2026-05-26 | `scripts/refinery-doctor.sh` — config drift detection + repair; 4 checks: embed-model, jcodemunch-scope, claude-md-sync, env-placeholders; atomic `--fix`; PR #13 |
| 2026-05-26 | `skill-link.sh` walks `global-skills/` — all globally promoted skills now auto-symlink on every session open; no manual `install-reliability.sh` needed after `git pull` |
| 2026-05-26 | 5 machine-local skills promoted to global — `pre-mortem`, `healthcheck-interactive-hints`, `mempalace-boot-repair-always-runs`, `platform-removal-cleanup`, `stop-hook-dedup-guard` |
| 2026-05-26 | `pre-mortem` skill restored — adversarial failure analysis (12 dimensions, WarGames escalation) synced from dma64 machine; discipline system fully operational |
| 2026-05-26 | `stack-not-at-head` resolved — jcodemunch-mcp 1.108.20 → 1.108.24; healthcheck path check relaxed to accept code-index venv |
| 2026-05-26 | `SessionStart` git fetch hook — async `git fetch --quiet` wired in `~/.claude/settings.json`; remote tracking state no longer stale at session open |
| 2026-05-26 | `uncle-j-mempalace-repair` cron restored — 4am nightly `mempalace repair` re-added to crontab; was dropped during `@reboot --skip-if-healthy` transition |
| 2026-05-25 | Blocking discipline hooks wired — `edit-surface-guard.sh` (pre-mortem gate on surface-list edits) and `grep-guard.sh` (routes `grep -r` to jcodemunch); `install-reliability.sh` now installs them on fresh machine |
| 2026-05-25 | `@reboot` repair made conditional (`--skip-if-healthy`); repair output now streams live |
| 2026-05-25 | MemPalace dict-format pickle root cause found — migrated `f89df21a` to `PersistentData`; fixed FTS5; fixed `mempalace-health.py` live query; added SessionStart health check hook |
| 2026-05-25 | `session-status-briefing` skill updated — now includes HANDOFF.md read and healthcheck.sh run as mandatory first steps |
| 2026-05-24 | MemPalace self-healing repair — FTS5 auto-rebuild pre-flight added to both `repair --yes` and `repair-hnsw rebuild` paths; 3 regression tests in repair.py, 2 in cli.py; fog-of-chess wing deleted (437K drawers); HNSW rebuilt clean at ~94K |
| 2026-05-24 | `mempalace-repair-verify.sh` — new verification script: SQLite vs HNSW count, FTS5 integrity check, semantic search smoke test |
| 2026-05-24 | `mempalace-delete-wing.py` — new utility: deletes a MemPalace wing by drawer prefix |
| 2026-05-23 | MemPalace HNSW permanent fix — `chroma-hnswlib==0.7.6` pinned in project deps; `CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI` set in all mine/repair/MCP scripts and crontab; health check thresholds corrected; stop hook routes via script |
| 2026-05-23 | MemPalace HNSW corruption root-cause fix — `hnsw:num_threads=1` on all collections neutralizes updatePoint race; health check now detects trillion-element header corruption; `mempalace-repair-now.sh` added |
| 2026-05-23 | Nightly MemPalace repair cron — 4am automated `mempalace repair` prevents HNSW drift; healthcheck detects drift and prompts repair |
| 2026-05-23 | Session-end checklist system — three-layer enforcement (skill → Stop hook → pre-commit block) |
| 2026-05-23 | Standard project docs — LICENSE (AGPL-3.0), CONTRIBUTING.md, SECURITY.md, ROADMAP.md |
| 2026-05-23 | `telegram-inline-button-promote` skill — inline keyboard button wiring pattern documented |
| 2026-05-23 | `session-end-checklist` skill symlinked — invocable as `/session-end-checklist` |
| 2026-05-23 | Telegram backlog age filter — drops messages >10 min old to prevent rate-limit burn |
| 2026-05-23 | `install.sh`: Telegram overwrite protection — `[y/N]` default, skip if not configured |
| 2026-05-23 | `install.sh`: Context7 API key setup — auto-reads `context7.key`, falls back to prompt |
| 2026-05-23 | Context7 API key configured — `~/.claude/.env` populated |
| 2026-05-23 | Git pull — merged 22 upstream commits; ECC agents, healthcheck-notify, new skills |
| 2026-05-22 | Telegram gateway notifications — healthcheck alerts, skill drafts, Ralph/dream FYIs |
| 2026-05-22 | Skill approval flow — auto-maintain drafts skills instead of auto-committing |

# ROADMAP — Uncle J's Refinery

Living roadmap. Updated at each session end when items complete or new ones surface.
Completed items age out after ~4 weeks.

---

## In Progress

- **Upstream MemPalace PR #1607** — FTS5 auto-rebuild before abort in `mempalace repair`; 5/6 CI jobs passing (Windows pending); awaiting maintainer review
- **turbovecdb parallel eval** — live as of 2026-06-04 (PR #23 merged); 296K drawers migrated, weekly benchmark + auto-report crons running; awaiting @kostadis response on recall@10 ef tuning

## Planned

- **Submit upstream MemPalace HNSW flush fix** — review `state/upstream-bug-report-hnsw-flush.md` + `state/upstream-pr-hnsw-flush.md`, submit to https://github.com/MemPalace/mempalace; once merged, remove force-flush Step 2b from `mempalace-repair-now.sh` and unpin `chromadb==1.5.8`

- **CI test job for `session-end-check.sh`** — add a pytest step to
  `.github/workflows/ci.yml` now that the test file exists

- **Telegram chat history persistence** — skill exists (`telegram-chat-history-persistence`)
  but implementation not yet started; would allow querying past bot conversations

- **Agent harness competitive analysis** — skill exists; full analysis not yet run

- **ECC specialist agents** — 6 agents imported; evaluate and integrate into
  active workflows

- **Expand discipline hook surface list** — after 1 week of `hook-blocks.log` data, review BLOCKED patterns and expand `edit-surface-guard.sh` surface list if coverage gaps appear; narrow if false positives are high

---

## Completed (recent)

| Date | Item |
|------|------|
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

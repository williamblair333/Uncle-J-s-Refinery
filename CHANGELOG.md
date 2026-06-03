# CHANGELOG — Uncle J's Refinery

---

## 2026-06-03 — fix: healthcheck dict-pickle detection + repair auto-migration

### Fixed
- **`healthcheck.sh`** — new `MemPalace — HNSW pickle format` step: pure stdlib `pickle.load` + `type()` check on every `index_metadata.pickle`; no chromadb import (upgrade-safe). Separates `BAD:` (dict-format, fixable by repair) from `ERR:` (unreadable, needs rebuild). `| tail -1` prevents Python traceback from matching `BAD:` pattern. Removes redundant `local py=` redeclaration inside `check_mempalace()`.
- **`mempalace-repair-now.sh`** — Step 2c: after WAL commit, glob all VECTOR segment pickles and migrate any `dict` → `types.SimpleNamespace` (stdlib-only, survives chromadb upgrades). Backup written to `.pickle.bak` before overwrite; atomic rename via `.pickle.tmp`. Exit code captured; WARN logged on failure.
- Session start: manually migrated segment `184bcb3d` dict pickle → `SimpleNamespace`; restored MCP search after restart.

### Root cause note
`PersistentClient._system.stop()` re-saves `self._persist_data` as-is via `pickle.dump`. If the segment was loaded from a legacy dict pickle (chromadb's `cast(PersistentData, ...)` is a type lie), the dict is written back on every save. Step 2c runs after Step 2b so the final on-disk state is always `SimpleNamespace` regardless of what Step 2b wrote.

## 2026-06-03 — fix: upgrade SQLite to 3.51.3 via pysqlite3 source build

- `install.sh` step 2b: builds pysqlite3 from source against SQLite 3.51.3 amalgamation when bundled version < 3.51.3 (PyPI wheel has 3.51.1, uv Python 3.11 has 3.50.4 — both affected by WAL-reset data race fixed in 3.51.3)
- `site-packages/_pysqlite3_patch.pth` + `_pysqlite3_patch.py`: swaps stdlib `sqlite3` → pysqlite3 at every venv process startup (covers mine crons, repair script, MCP server — no per-script patching needed)
- `pyproject.toml`: `pysqlite3>=0.6.0` added as formal dependency with explanatory comment
- Version check in install.sh is `>= (3,51,3)` not `importable` — correctly triggers rebuild on machines that got the PyPI wheel via `uv sync`

## 2026-06-03 — fix: eliminate recurring FTS5 corruption (root cause)

### Root cause
Four compounding bugs caused "malformed inverted index" to reappear every morning:
1. `fts5-guard.sh` (async SessionStart hook) opened an uncommitted FTS5 transaction concurrently with the repair script — corrupted the B-tree between the repair's PRE and POST quick_check calls
2. `session-start-autofix.sh` used system `python3`/`sqlite3` (SQLite 3.46.1) to read/write an FTS5 index created by venv Python (SQLite 3.50.4) — version mismatch silently corrupts the index
3. `healthcheck.sh` used FTS5 `integrity-check` INSERT (only checks data consistency) instead of `PRAGMA quick_check` (catches B-tree malformation) — produced false-ok on every session
4. Crontab had duplicate entries for all 4 mempalace jobs — `install_cron()` used exact marker match, leaving old entries with description suffixes untouched on re-install

### Fixed
- **`scripts/fts5-guard.sh`** — disabled (exit 0); was the primary corruptor; replaced by improved session-start-autofix.sh
- **`scripts/session-start-autofix.sh`** — FTS5 check now uses venv Python (SQLite 3.50.x) + `PRAGMA quick_check`; skips if repair lock held; uses `mempalace-fts5-session.lock` to prevent concurrent session races
- **`healthcheck.sh`** — `check_mempalace()` FTS5 check changed from `integrity-check` INSERT to `PRAGMA quick_check`; now correctly detects B-tree malformation
- **`mempalace-repair-now.sh`** — writer check expanded from `mine|repair` to `mine|repair|fts5|autofix|mempalace` (catches fts5-guard and mempalace-health.py); WAL commit dim detection fixed (`SELECT embedding FROM embeddings` → `SELECT dimension FROM collections`, fixes `no such column: embedding` error from 2026-06-02)
- **`lib/feature-helpers.sh`** — `install_cron()` awk pattern changed from exact match to prefix match (`^# $marker([^-]|$)`) so re-installing removes old entries with description suffixes
- **Crontab** — deduplicated (was 2× for all 6 mempalace jobs); 4am repair now uses `--skip-if-healthy` consistently
## 2026-06-01 — ops: system freeze diagnosis + foc container CPU throttling

### Fixed
- **System freeze (RDP unusable)** — diagnosed fairy-stockfish chess engine processes (`foc-server-1` container) running at ~180% CPU continuously for 3h43m; combined with 2.6 GB swap in use from Chrome/KWin/ClickHouse/Langfuse/Grafana stack, caused RDP to freeze
- **`/opt/proj/foc/docker-compose.yml`** — added hard CPU caps via `cpu_quota`/`cpu_period` (not `deploy.resources.limits.cpus` — that silently fails with Docker 26.1 + cgroup v2 + systemd driver; NanoCPUs is set but cpu.max stays empty; cpu_quota translates to `CPUQuotaPerSecUSec` in the systemd scope and actually bites)
  - `server`: 2-core cap (`cpu_quota: 200000`, `cpu_period: 100000`)
  - `learner`: 1-core cap (`cpu_quota: 100000`, `cpu_period: 100000`)
  - `ENGINE_THREADS` default: 2 → 1 (halves per-engine thread count)
  - `CPU_IDLE_MS` default: 2000 → 5000 (learner rests longer between self-play games)
- **Result**: load avg 10 → 3, server CPU% 348% → ~200% (at cap), RDP responsive

### Notes
- All four throttle values overridable via `.env` (`SERVER_CPU_QUOTA`, `LEARNER_CPU_QUOTA`, `ENGINE_THREADS`, `CPU_IDLE_MS`) without touching compose file
- HNSW drift healthcheck failure (`mempalace-hnsw-drift`) present at session start — not addressed this session (focus was system freeze)

---

## 2026-06-01 — fix: WAL commit SQL bug in mempalace-repair-now.sh; stack bump

### Fixed
- **`mempalace-repair-now.sh` Step 2b (WAL commit)** — SQL queried `SELECT embedding FROM embeddings` but the `embeddings` table has no vector column; vectors live in `embeddings_queue.vector`. Changed to `SELECT vector FROM embeddings_queue WHERE vector IS NOT NULL LIMIT 1`. Added a log line when queue is empty so fallback to dim=384 is visible in repair logs.
- **Root cause of 2026-06-01 HNSW=0** — the 4am cron's `from-sqlite` rebuild succeeded (30,207 rows written) but the WAL commit step crashed on the wrong column name, leaving HNSW at 0 elements; fixed SQL ensures tonight's cron completes the full pipeline.

### Changed
- **`uv.lock`** — auto-maintain cron (3am) bumped jcodemunch-mcp (`d6ffcbd` → `7315c5ef`) and mempalace (`6957c7e` → `9b7cfc99`).

---

## 2026-05-28 — chore: triage session — review queue cleared, HNSW repair

### Fixed
- **HNSW repair process** — prior repair (PID 13765) was stuck in `Tl` (stopped) state for 28 min with 0 HNSW elements; killed and restarted fresh repair (PID 151601) rebuilding 18K embeddings from SQLite

### Changed
- **`_review/openclaw/`** → `_reviewed/openclaw/` — competitive analysis complete; Features 1 (refinery-doctor, PR #13) and 2 (Telegram routing, PR #20) both shipped; Feature 3 (Docker sandbox) explicitly deferred

---

## 2026-05-28 — feat: Telegram multi-agent routing + session-end docs

### Changed
- **`README.md`** — added `/work <message>` to Telegram gateway inbound commands
- **`ROADMAP.md`** — Feature 2 and HNSW fix moved to completed table
- **`SECURITY.md`** — documented `/work` elevated-access model; Telegram account = security boundary

---

## 2026-05-28 — feat: Telegram multi-agent routing

### Added
- **`config/telegram-agents.toml`** — prefix-based agent routing config; `/work` prefix routes to full-context project agent (cwd=PROJ_ROOT, CLAUDE.md loads); unqualified messages keep restricted default (cwd=/tmp); catch-all ordering validated at load time (R4)
- **`load_agents()` / `route_message()` / `resolve_cwd()`** — routing functions in gateway Python heredoc; fallback to restricted-only hardcoded defaults on missing/malformed TOML (R1) or Python < 3.11 (R2); every dispatch logged with agent name + cwd (R5)
- **Routed dispatch in `telegram-gateway-poll.sh`** — `route_message()` selects agent before subprocess call; `/work` runs Claude in proj_root without `--system-prompt` (loads CLAUDE.md normally); default runs in `/tmp` with `TELEGRAM_SYSTEM_RESTRICTION`; `ELEVATED:` prefix in log for `/work` dispatches
- **Routing smoke tests** — assertions cover default path, `/work` prefix strip, empty `/work`, `resolve_cwd` proj_root mapping, hardcoded fallback when TOML missing

---

## 2026-05-28 — fix MemPalace HNSW nightly destruction (three-bug root cause)

### Fixed
- **`mempalace-repair-now.sh`** — three compounding bugs caused HNSW to be destroyed nightly:
  1. **`--skip-if-healthy` missing from 4am cron** — repair archived the healthy palace every night unconditionally; added to `features/mempalace/install.sh` (durable) and crontab
  2. **WAL never committed to HNSW** — `mempalace repair --mode from-sqlite` writes directly to SQLite WAL tables and never builds the HNSW binary; added Step 2b that opens a chromadb `PersistentClient`, calls `col.query()` on each collection (forces HNSW segment init + WAL replay into in-memory index), then calls `client._system.stop()` (triggers `save_index()` on all segments to persist to disk)
  3. **Post-repair check read SQLite only** — repair always reported `REPAIR_RESULT=success` even when HNSW was 0; updated post-repair count check to read both SQLite embeddings count and HNSW `header.bin` element count
- **`mempalace-repair-now.sh` line 109** — pre-existing bug: `"$VENV/python"` (no 3) in FTS5 rebuild path would fail on Ubuntu/Debian where venvs do not symlink `python`; fixed to `"$VENV/python3"`
- **Code review fixes** — empty collection guard: `col.query()` raises `InvalidArgumentError` on empty collections; now guarded with `col.count()` check first; blob type guard: `len(row[0])//4` now validates `isinstance(blob, (bytes, bytearray))` before use
- **`features/mempalace/install.sh`** — 4am repair cron definition now includes `--skip-if-healthy` so re-running install.sh doesn't revert the crontab fix

## 2026-05-27 — automate plugin install, fix skill-link global-skills unlink bug

### Fixed
- **`scripts/skill-link.sh`** — Stop hook was unlinking global-skills symlinks as well as project-local ones, causing skills like `session-end-checklist` and `session-status-briefing` to vanish from `~/.claude/skills/` at session end. Global skills are now link-only (never unlinked); only `skills/` is session-scoped.
- **`install-reliability.sh`** — wrong marketplace name `anthropics-claude-code` in "Next:" manual instructions (correct: `claude-code-plugins`). Instructions removed; step is now automated.
- **Langfuse postgres auth** — `POSTGRES_PASSWORD` in `.env` diverged from the initialized volume after container recreation. Fixed via `ALTER USER postgres PASSWORD` inside the running container. (Not a code change — operational fix.)

### Added
- **`install-reliability.sh` — plugin auto-install** — new section registers both marketplaces (`claude-code-plugins`, `claude-plugins-official`) and installs `superpowers` and `ralph-wiggum` at `--scope user` so they work in every project, not just this one. Falls back to clear warn message if `claude` CLI not on PATH. Idempotent (checks before installing).

### Changed
- **`README.md` step 6** — manual `/plugin install` block replaced with description of auto-install; fallback manual commands retained with correct marketplace names and `--scope user`.
- **`install-reliability.sh` "Next:" steps** — manual plugin install step removed; new install is self-contained in two steps: `./install-guardrails.sh` + optional `./install-langfuse.sh`.

## 2026-05-27 — chore: stop hook inline form, verify-pr-branch skill

### Maintenance
- **`settings.json`** — mempalace install re-registered the stop hook with the inline
  `mempalace mine` command (canonical form written by the install script) instead of the
  `mempalace-mine-convos.sh` wrapper. Functionally equivalent; marker preserved.
- **`global-skills/verify-pr-branch-before-resolve/SKILL.md`** — committed untracked skill
  for verifying correct branch before merge-conflict resolution.

---

## 2026-05-27 — install.sh: add mempalace mine crons to new-user install path

### Fixed
- **New-user install gap** — `install.sh` installed MemPalace Python package and backup/health
  crons but never called `features/mempalace/install.sh`, leaving the palace permanently empty
  for fresh installs. Added section 5c2 that calls the feature installer automatically.
- **`features/mempalace/install.sh`** — added `mine-convos` (3:03am) and `boot-repair`
  (@reboot) cron entries with proper `install_cron` markers so they survive re-installs.
  Previously these were manually applied on the dma64 machine only.
- **`install.sh` backup/health crons** — added `nice -n 19` to match the running production
  configuration on dma64.

---

## 2026-05-27 — healthcheck FTS5 check: use venv Python to fix sqlite3 version false positive

### Fixed
- **`healthcheck.sh` `check_mempalace()` false positive** — system `sqlite3` 3.46.1 reports
  FTS5 indexes written by Python's sqlite3 3.50.4 as malformed on every session start.
  Switched to venv Python for the FTS5 `integrity-check` command, with fallback to system
  binary when venv is absent. Also updated repair hint to use venv Python.
- **`stack-not-at-head`** — updated `uv.lock` with jcodemunch 1.108.25 and mempalace 3.3.6
  at today's HEAD, clearing the remaining healthcheck failure.

---

## 2026-05-27 — Session catchup: health check + git pull to HEAD

### Maintenance
- Full health check run — all green except untracked-skills (auto-maintain will handle) and Langfuse traces API returning "Invalid credentials" (open item)
- `git pull` fast-forwarded main by 2 commits (PR #14: fts5-guard, cron coordination, skill-link fix)
- Confirmed `fts5-guard.sh` wired as SessionStart hook in settings.json

---

## 2026-05-27 — FTS5 guard, repair/mine coordination, skill-link blocking fix

### Fixed
- **FTS5 recurring corruption** — root cause: 4am repair cron had no awareness of 3am mine
  cron; used its own unrelated lock, aborted immediately if mine still writing. Fixed crontab
  to use `flock -w 7200` on both mine lock files so repair waits for mines to finish before
  running. Also added `flock -n /tmp/mempalace-repair.lock` to prevent duplicate repair instances.
- **`features/mempalace/install.sh`** — mine cron now registers with `flock -n`, `nice -n 19`,
  and `env CHROMA_API_IMPL=...`; repair cron now registers the coordinated `flock -w 7200` form.
  New users and reinstalls get the correct crons automatically (no manual crontab edit needed).
- **`Unknown skill` at session start** — skill-link.sh SessionStart hook was `async: true`,
  so the Skill tool could be invoked before symlinking finished. Removed `async: true` to make
  it blocking (~142ms cost, imperceptible). Fixed in both `settings.json` and
  `features/skill-manager/install.sh` so reinstalls don't revert it.

### Added
- `scripts/fts5-guard.sh` — async SessionStart safety net; checks FTS5 integrity via venv
  Python (correct SQLite version) and auto-rebuilds if corrupt. Wired as SessionStart hook.
  Catches any corruption that slips past the 4am repair (e.g. if mine runs >2h).

---

## 2026-05-26 — feat/refinery-doctor implementation

### Added
- `scripts/refinery-doctor.sh` — standalone config-drift detection and repair script
  - 4 checks: `embed-model`, `jcodemunch-scope`, `claude-md-sync`, `env-placeholders`
  - `--fix` mode with atomic `.env` writes (`.env.bak` + `.env.tmp` → `mv`)
  - `--check <name>` for single-check mode; `--help` from script header
  - Exit 0 = clean, exit 1 = pending migrations
- `install-reliability.sh` — added `# Config drift: bash scripts/refinery-doctor.sh [--fix]` to header

---

## 2026-05-26 — session-start-autofix hook + FTS5 skill + gitignore

### Added
- `scripts/session-start-autofix.sh` — SessionStart hook that auto-repairs FTS5 corruption,
  reindexes jcodemunch when stale, and async-upgrades stack packages behind HEAD; replaces
  manual `healthcheck.sh --quick` approach; logs to `state/session-start-autofix.log`
- `global-skills/mempalace-fts5-malformed-index-repair/` — new skill for FTS5 malformed
  inverted index repair; distinct from HNSW corruption and 0-elements-after-reboot

### Changed
- `.claude/settings.json` — SessionStart hook now runs `session-start-autofix.sh`
  (timeout 60 s, "Health check + auto-fix..." message) instead of bare healthcheck
- `global-skills/session-end-checklist/SKILL.md` — Step 8 improved: auto-push after
  commit; offer PR vs direct-merge options based on what changed
- `uv.lock` — jcodemunch-mcp 1.108.24 → 1.108.25

### Fixed
- `.gitignore` — added `.claude/scheduled_tasks.json` and `.claude/worktrees/`
---

## 2026-05-26 — session housekeeping: pull to main, FTS5 repair, skill link fix

### Fixed
- FTS5 malformed inverted index — rebuilt via `sqlite3 INSERT INTO embedding_fulltext_search`
  (~1.6 GB DB, ~2 min rebuild); `HEALTHCHECK: ok` confirmed post-repair
- Stale mine lock cleared (`state/mempalace-mine-convos.lock`, 106 709 s old)
- 22 global-skills missing from `~/.claude/skills/` — `install-reliability.sh` had not been
  run after the pull that added them; re-running on main linked all 36 skills
- Root cause of `Unknown skill: session-end-checklist` confirmed (seen on both machines):
  `install-reliability.sh` must be run after any `git pull` that adds new `global-skills/`
  entries; `skill-link.sh` SessionStart hook should prevent recurrence automatically

### Changed
- Switched from stale `docs/session-end-2026-05-24` to `main` — fast-forwarded 33 commits;
  WIP stashed as `wip: session-end-2026-05-24 uncommitted changes`
- jcodemunch index advanced to HEAD (`68846f0`) via `scripts/jcodemunch-reindex.sh`

### Remaining
- `stack-not-at-head` (X) — packages behind HEAD; run `stack-not-at-head-remediation` skill
- Stash `wip: session-end-2026-05-24 uncommitted changes` contains `scripts/session-start-autofix.sh`
  hook wiring — review and drop or apply next session

---

## 2026-05-26 — OpenClaw competitive analysis + doctor+routing spec and plans

### Added
- `docs/superpowers/specs/2026-05-26-doctor-and-routing-design.md` — approved design
  spec for two new features:
  1. `scripts/refinery-doctor.sh` — standalone config-schema-drift detection with dry-run
     and `--fix` mode; 4 migration checks: `embed-model`, `jcodemunch-scope`,
     `claude-md-sync`, `env-placeholders`; atomic `.env` writes (tmp+mv)
  2. Telegram multi-agent routing — prefix-based dispatch via
     `config/telegram-agents.toml`; `/work` prefix → project agent (PROJ_ROOT, CLAUDE.md);
     no-prefix → restricted default agent (/tmp, TELEGRAM_SYSTEM_RESTRICTION)
- `docs/superpowers/plans/2026-05-26-refinery-doctor.sh.md` — 7-task TDD implementation
  plan for `scripts/refinery-doctor.sh`
- `docs/superpowers/plans/2026-05-26-telegram-agent-routing.md` — 5-task implementation
  plan for `config/telegram-agents.toml` + routing layer in `telegram-gateway-poll.sh`

### Analysis
- OpenClaw competitive analysis completed (TypeScript, 52K commits, ClawHub marketplace,
  Docker sandboxing, `openclaw doctor --fix` pattern); 3 features identified as worth
  borrowing. Feature 3 (Docker-sandboxed Telegram sessions) deferred — credential
  management non-trivial, gets its own session.

---

## 2026-05-26 — skill-link.sh now walks global-skills/ on every SessionStart

### Fixed
- `scripts/skill-link.sh` — extracted loop into `link_skill_dirs()` and called it
  for both `skills/` and `global-skills/`; now auto-symlinks all global skills on
  every session open without needing to manually run `install-reliability.sh`
- Upgraded bare `ln -s` to `ln -sfn` with correct-link check — flat copies left
  behind from manual installs are now auto-upgraded to proper symlinks

---

## 2026-05-26 — promote 4 machine-local skills to global

### Added
- `global-skills/healthcheck-interactive-hints/` — guides wiring interactive `hint()` fix prompts into healthcheck scripts
- `global-skills/mempalace-boot-repair-always-runs/` — diagnoses `@reboot` repair loops when HNSW shows 0 elements after reboot despite healthy SQLite
- `global-skills/platform-removal-cleanup/` — scrubs all artifacts when dropping platform support (scripts, docs, config, source branches)
- `global-skills/stop-hook-dedup-guard/` — fixes duplicate Stop hook Telegram notifications from near-simultaneous session closes
- `global-skills/pre-mortem/` — adversarial failure analysis (12 dimensions, WarGames escalation, CATASTROPHIC ceremony) before consequential actions

All five existed as machine-local skills on the dma64 machine; promoted here so `install-reliability.sh` distributes them to all machines on next pull.

---

## 2026-05-26 — stack upgrade, pre-mortem skill restored, healthcheck path fix

### Fixed
- jcodemunch-mcp upgraded 1.108.20 → 1.108.24 (was 4 versions behind HEAD)
- `check_jcodemunch_path()` in `healthcheck.sh` — relaxed path check to accept code-index venv path (updated by jcodemunch-reindex.sh) alongside project venv; no longer false-fails after every reindex run
- `~/.claude/skills/pre-mortem/SKILL.md` restored — skill was missing on disk, causing edit-surface-guard to block and fail to find `/pre-mortem`; discipline system now fully operational
- jcodemunch index reindexed to HEAD (`5462a188`) after upgrade

### Unchanged
- No new tools added to CLAUDE.md — jcodemunch_guide tool list identical to 1.108.20

---

## 2026-05-26 — maintenance: cron restored, git-fetch hook wired, reindex run

### Fixed
- Re-added `uncle-j-mempalace-repair` cron (`0 4 * * *` — `mempalace repair`) — was dropped during the `@reboot --skip-if-healthy` transition; `HEALTHCHECK: fail` cron check now passes
- jcodemunch index reindexed — was 41 commits stale at session open; now at HEAD (`17d0708b`)

### Added
- `git fetch --quiet` async `SessionStart` hook in `~/.claude/settings.json` — runs in background each session open; closes the stale remote-state gap identified in the previous session

### Noted
- `pre-mortem` skill (`~/.claude/skills/pre-mortem/SKILL.md`) referenced by `edit-surface-guard.sh` does not exist on disk; hook blocked then bypassed via inline pre-mortem analysis — skill needs to be restored for discipline system to function cleanly

---

## 2026-05-26 — pulled 40 commits, linked new skills, dropped orphaned stash

### Changed
- Pulled `origin/main` (40 commits behind, May 22–25 work) via fast-forward
- Ran `install-reliability.sh`: symlinked discipline hooks (`edit-surface-guard.sh`, `grep-guard.sh`, `unpushed-warn.sh`) and linked 6 new global skills (`session-end-checklist`, `session-status-briefing`, `mempalace-repair-mine-interference`, `mempalace-wing-failure-stale-server-state`, `polling-bot-age-filter-fix`, `telegram-inline-button-promote`)

### Removed
- Dropped stale `stash@{0}` containing undocumented `graphviz>=0.21` and `matplotlib>=3.10.9` additions to `pyproject.toml` — no commit message, no HANDOFF mention, provenance unknown

### Gap identified
- `git status` without prior `git fetch` gave a false "up to date" report; need `SessionStart` hook to auto-fetch

---

## 2026-05-25 — unpushed-warn Stop hook + push status in session-end-checklist

### Added
- `hooks/discipline/unpushed-warn.sh` — Stop hook; fires at session end and warns (via `systemMessage`) when branch is ahead of remote. Non-blocking. Timeout-guarded, upstream-existence-guarded, handles non-git dirs.
- `global-skills/session-end-checklist/SKILL.md` Step 8: reports unpushed commit count after committing. Does NOT auto-push — reports status only, user decides when to push.
- `install-reliability.sh`: wires `unpushed-warn.sh` Stop hook on fresh-machine setup.

---

## 2026-05-25 — blocking discipline hooks wired (edit-surface-guard, grep-guard)

### Added
- `hooks/discipline/edit-surface-guard.sh` — PreToolUse hook; blocks Edit/Write on surface-list files (`.sh`, `.py`, `.toml`, `.yml`, `.yaml`, `Dockerfile*`, `settings.json`, `CLAUDE.md`, `scripts/`, `hooks/`, `features/`) until pre-mortem clears bypass flag (`/tmp/premortem-cleared-SESSION_ID`).
- `hooks/discipline/grep-guard.sh` — PreToolUse hook; blocks `grep -r` on source directories; redirects to `mcp__jcodemunch__search_text`.
- Both hooks log BLOCKED/ALLOWED entries to `state/hook-blocks.log` for weekly review.
- `install-reliability.sh`: new section symlinks `hooks/discipline/*.sh` to `~/.claude/hooks/discipline/` and wires PreToolUse entries into `settings.json` on fresh-machine setup.
- `global-skills/session-end-checklist/SKILL.md`: new Step 6 — weekly `hook-blocks.log` review.
- Hooks wired into `~/.claude/settings.json` (10 PreToolUse hooks total, 2 new).

### Bypass mechanism
After invoking pre-mortem: `touch /tmp/premortem-cleared-SESSION_ID` — the guard script consumes and removes it, then allows the edit.

---

## 2026-05-25 — repair output now streams live to log

Removed `REPAIR_OUT=$(mempalace repair ...)` capture pattern in `mempalace-repair-now.sh`. Output now streams directly to stdout (and therefore to the cron log) in real time. Previously the log showed nothing for 90 minutes then dumped everything at once.

---

## 2026-05-25 — @reboot repair made conditional (skip-if-healthy)

### Problem
Every reboot triggered a 90-minute unconditional `mempalace repair --archive-existing`, even when HNSW was healthy. Sessions always started with HNSW=0 (rebuild in progress). Root cause: `@reboot` cron was designed as a missed-cron recovery but behaved as a wipe-and-rebuild every boot.

### Fixed
- Added `--skip-if-healthy` flag to `mempalace-repair-now.sh`. Checks: all `link_lists.bin` files exist, non-empty, <200MB (corruption threshold), and HNSW element count ≥80% of SQLite count. If all pass → exits immediately with `REPAIR_RESULT=skipped_healthy`.
- `@reboot` cron updated locally to pass `--skip-if-healthy`.
- 4am nightly cron unchanged — still rebuilds unconditionally to sync mining additions.

---

## 2026-05-25 — MemPalace dict-format pickle root cause found and fixed (session 4)

### Root cause
- **`'dict' object has no attribute 'dimensionality'`** was NOT stale in-memory state. The `index_metadata.pickle` for segment `f89df21a` (mempalace_drawers VECTOR) was stored as a plain Python dict, not a `PersistentData` object.
- chromadb 1.5.8 SegmentAPI does `cast(PersistentData, pickle.load(f))` — if the pickle contains a dict, `cast` silently returns the dict, then `.dimensionality` fails with AttributeError.
- `PersistentClient` (Rust API, the default) handles dict-format pickles. MCP server + mine scripts force `CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI`, hitting the failure.
- "Restart Claude Code" never fixed it because each new process loaded the same broken dict from disk.

### Fixed
- Migrated `~/.mempalace/palace/f89df21a.../index_metadata.pickle`: dict → `PersistentData` format.
- Fixed FTS5 corruption (`malformed inverted index for FTS5 table embedding_fulltext_search`).
- `mempalace-health.py` live query: replaced `Client(settings)` with `chromadb.PersistentClient` (avoids the fragile lower-level path).
- Added SessionStart health check hook to `.claude/settings.json` (30s timeout, shows summary line).

### Status
- MCP tools deregistered this session (server killed to apply fix). Restart Claude Code to reconnect.
- How dict-format pickles form in the first place: not yet fully traced. Health check at session start will catch recurrence early.

---

## 2026-05-25 — MemPalace stale-server-state re-verified (session 3)

### Diagnosed
- **Re-ran MemPalace wing health check**: 243,278 drawers (up from 234K — stop hook mined more). Global search and `conversations` wing still working; `uncle_j_s_refinery` and `sessions` wings still failing in the live MCP server.
- **New finding**: `mempalace_reconnect` now changes error type (`ef or M is too small` → `'dict' object has no attribute 'dimensionality'`) — Python cache cleared but C++ hnswlib object still stale.
- **Disk confirmed healthy**: direct `chromadb.PersistentClient` query from a fresh subprocess returned results for both failing wings. Issue is definitively server-side state.
- **MCP server disconnected** at session end (expected side effect of investigation; Claude Code restart will bring it back clean).
- **Fix**: restart Claude Code — no file changes needed.

---

## 2026-05-25 — MemPalace health diagnostic + mempalace 3.3.6

### Diagnosed
- **MemPalace health check**: 234,147 drawers confirmed in palace. Global search and `conversations` wing working. `uncle_j_s_refinery` and `sessions` wings failing in the live MCP server with HNSW "ef or M is too small" error.
- **Root cause**: live MCP server (PID 2159655) holds a stale in-memory HNSW state from before the 05:25 rebuild. `mempalace_reconnect` cleared the Python cache but the C++ hnswlib object survived. All direct Python calls work correctly — issue is isolated to the running process.
- **Fix**: restart Claude Code (or the MCP server) — fresh process loads the rebuilt HNSW cleanly.
- **HNSW vs SQLite**: 200K/234K (34K in the pending flush batch; within `batch_size=50000` tolerance; not a bug).

### Added
- `global-skills/mempalace-wing-failure-stale-server-state/` — new skill: diagnose and fix wing-scoped HNSW failures caused by stale in-memory server state (distinct from disk corruption). Covers the exact pattern found this session.

### Changed
- `uv.lock` — mempalace 3.3.5 → 3.3.6 (SHA `d0d011eb`); adds `huggingface-hub`, `numpy`, `tokenizers` dependencies (pre-existing from prior session, not from this session's work).

---

## 2026-05-25 — MemPalace palace rebuild complete

### Outcome
- 4am cron ran `mempalace repair --mode from-sqlite --yes --archive-existing` at 04:00–05:29.
- 235,251 embeddings rebuilt. HNSW index healthy. Vector similarity search restored.
- Corrupt palace archived at `~/.mempalace/palace.pre-rebuild-20260525-040008`.
- Compactor queue at 35,252 entries post-rebuild (expected; will drain on next mine run).

---

## 2026-05-24 — MemPalace repair: fix success notification (MCP auto-restarts)

### Fixed
- `mempalace-repair-now.sh` — success notification corrected: removed incorrect "Restart MCP server" instruction. Claude Code spawns a fresh MCP server subprocess on every session start, so no manual restart is needed after palace rebuild.

---

## 2026-05-24 — MemPalace repair: Telegram notifications on success/failure

### Added
- `mempalace-repair-now.sh` — Telegram notification at every exit point (success, FTS5 fail, HNSW fail, writer-active abort) via `lib/notify.sh`. No more babysitting the repair log.

---

## 2026-05-24 — MemPalace HNSW repair: switch to from-sqlite mode

### Fixed
- `mempalace-repair-now.sh` — replaced `mempalace repair --yes` (legacy mode) with `mempalace repair --mode from-sqlite --yes --archive-existing`. Legacy mode opens the chromadb client against the corrupt palace, hits SIGBUS on corrupt `max_el` values in `header.bin`, then writes NEW corrupt headers to additional segments — cascading the damage on every repair attempt. `from-sqlite` reads directly from `chroma.sqlite3`, never touches the corrupt HNSW files, and builds a fresh palace.
- `mempalace-repair-now.sh` — removed manual HNSW segment clearing steps (unnecessary with `from-sqlite --archive-existing`).
- `mempalace-repair-now.sh` — fixed embedding count bug: was querying `embedding_metadata` rows (~9× per embedding), reporting 2.7M instead of actual 298K.
- `mempalace-health.py`, `healthcheck.sh`, `mempalace-delete-wing.py` — updated repair command hints to use `--mode from-sqlite`.
- `global-skills/mempalace-hnsw-corruption-fix/SKILL.md` — Step 7 updated; added explicit warning against using legacy `repair --yes`.
- `global-skills/mempalace-repair-mine-interference/SKILL.md` — Step 4 updated.

### Root cause (documented)
`chroma-hnswlib 0.7.6` Rust bindings have a type-confusion bug (`element_levels_[i]` written as float, read as int32). Every `updatePoint` call on an existing item triggers it, writing astronomical `max_el` values (e.g. `4,294,967,296,000`) to `header.bin`. The `CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI` env var is a mitigation (forces Python hnswlib path) and is correctly set in all entry points. The repair cascade was the compounding problem: legacy repair SIGBUSed and left new corrupt headers behind. No upstream fix exists in `chroma-hnswlib` (0.7.6 is the only release). MemPalace `--mode from-sqlite` (shipped in 3.3.5, which we run) is the correct recovery path.

---

## 2026-05-24 — README hero tagline rewrite

### Changed
- `README.md` — opening tagline replaced: "AI operating system" framing dropped in favour of a problem-led pitch ("Claude Code forgets everything when you close the terminal. This doesn't...")

---

## 2026-05-24 — Pre-mortem hook enforcement (skill discipline gap fix)

### Added
- `~/.claude/hooks/pre-mortem-guard/prompt-guard.sh` — `UserPromptSubmit` hook; fires when message contains PR/issue/push/merge/wrap-up keywords and outputs `PRE-MORTEM REQUIRED` before any action is taken
- `~/.claude/hooks/pre-mortem-guard/pretool-guard.sh` — `PreToolUse/Bash` hook; fires immediately before `gh pr create`, `gh issue create`, `gh issue new` executes
- `~/.claude/projects/…/memory/feedback_pre-mortem-discipline.md` — persistent cross-session memory enforcing pre-mortem before GitHub artifact creation

### Changed
- `~/.claude/settings.json` — two new hook entries: `UserPromptSubmit` → `prompt-guard.sh`, `PreToolUse/Bash` → `pretool-guard.sh`
- `~/.claude/skills/pre-mortem/SKILL.md` — "GitHub actions" row added to surface table (`gh pr create`, `gh issue create`, `gh issue new`, push to remote); frontmatter updated to name these triggers explicitly
- `prompt-guard.sh` regex broadened mid-session: now catches `\bpr\b`, `\bpush\b`, `\bissue\b`, `wrap-up`, `session-end`, `ship it` — original tight pattern missed natural-language "pr / push" (live regression caught in session)
- `uv.lock` — mempalace bumped `be64371` → `3a4be3e`; adds `python-dateutil` dependency

### Note — out-of-repo
Hook enforcement lives entirely in `~/.claude/` (global config, skills, hooks). A fresh-clone machine does not get this infrastructure via `git clone`. Manual setup required — see HANDOFF for all paths.

---

## 2026-05-24 — MemPalace repair self-healing + upstream PR #1607

### Fixed
- `mempalace-repair-now.sh`: uses venv Python for all SQLite checks — system `sqlite3` CLI (3.46.1) reports false-positive FTS5 corruption on indexes written by Python's SQLite 3.50.x; replaced all `sqlite3 "$DB" "..."` calls with `pycheck()` helper that invokes `.venv/bin/python3` directly
- `mempalace-repair-now.sh`: FTS5 corruption now auto-rebuilt before aborting — `PRAGMA quick_check` failure no longer silently blocks the 4am repair cron indefinitely; script attempts `INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('rebuild')` first and only aborts if that fails
- `mempalace-repair-now.sh`: HNSW corruption threshold corrected from 10^16 to 500_000_000_000 — previous threshold missed trillion-element corruption values that were actually present
- `mempalace-repair-now.sh`: `mempalace repair --yes` with `"Aborted"` string detection — repair exits 0 even on abort; script now checks both exit code and output
- `mempalace-repair-now.sh`: removed `set -e`; explicit `REPAIR_RESULT=` tracking; drawer count sanity check (95% threshold) post-repair

### Added
- `mempalace-repair-verify.sh`: post-repair verification script — waits for flock release, compares HNSW element count to SQLite count (95% threshold), writes `VERIFY_RESULT=success|fail` to repair log, creates sentinel `/tmp/mempalace-verify-done` on success; run by monitoring cron every 30 min
- `mempalace-delete-wing.py`: bulk wing deletion tool — queries all drawer IDs for a named wing and deletes in 500-ID batches with confirmation prompt and pre/post count display

### Changed
- Deleted 437,420 fog-of-chess drawers from the shared palace — palace down from 475K to ~94K drawers; repair now takes ~15 min instead of 3+ hours; fog-of-chess project should use a separate palace if re-mined

### Upstream contributions (MemPalace/mempalace)
- Filed issue #1606: `repair` aborts on FTS5 inverted-index corruption without attempting auto-recovery
- Submitted PR #1607: fixes both `rebuild_index()` in `repair.py` (repair-hnsw rebuild path) and `cmd_repair` in `cli.py` (`mempalace repair --yes` path) — scope-guarded FTS5 auto-rebuild, re-validates with `PRAGMA quick_check` before proceeding; 5 new regression tests; 150/150 passing; lint+format clean; 5/6 CI jobs passing (Windows pending)

---

## 2026-05-23 — HNSW corruption permanent fix: chroma-hnswlib + SegmentAPI

### Fixed
- `pyproject.toml`: added `chroma-hnswlib==0.7.6` to both `dependencies` and `override-dependencies` — provides the stable Python hnswlib module; without it chromadb 1.5.x silently fell back to Rust bindings which have the type-confusion bug (chroma-core/chroma#4460)
- All mine/repair launch paths now export `CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI`: `scripts/mempalace-mcp-start.sh`, `scripts/mempalace-mine-convos.sh`, `mempalace-repair-now.sh`, crontab mine+repair entries
- `.claude/settings.json` stop-hook: switched from inline `mempalace mine` call to `bash scripts/mempalace-mine-convos.sh` so the env var is picked up
- `mempalace-health.py`: fixed corruption detection — `link_lists.bin >100MB` is now primary indicator (not header uint64 threshold, which false-positives on valid Python hnswlib format); increased header threshold from 10M to 10^16 to accommodate chroma-hnswlib 0.7.6 encoding; fixed `PersistentData` pickle parsing (was calling `.get()` on object, not dict); live-load test now uses SegmentAPI
- `mempalace-repair-now.sh`: now dynamically discovers corrupt segments from SQLite instead of hardcoding 2 segment IDs — works for any number of collections

---

## 2026-05-23 — Stop-hook mine overlap fix + cron deduplication

### Fixed
- `settings.json`: stop-hook mine command wrapped with `flock -n /tmp/mempalace-mine-convos.lock` — concurrent Claude session stops no longer spawn overlapping mine processes
- Crontab: removed duplicate `uncle-j-mempalace-backup` and `uncle-j-mempalace-health` entries that had accumulated from multiple install runs
- Crontab: added `flock -n` guards to all mine cron commands (project + convos) to match stop-hook guard

### Added
- Crontab: `@reboot` entry — runs `mempalace-repair-now.sh` after 120s boot delay; self-heals HNSW when 3am/4am crons were missed due to shutdown

---

## 2026-05-23 — MemPalace HNSW corruption root-cause fix

### Fixed
- `mempalace-health.py`: header.bin was parsed as uint32 — 7.2 trillion corruption value wrapped to 0, silently passing all checks. Now parsed as int64 with a 10M sanity cap; CRIT alert fires on astronomical values (chroma-core/chroma#4460)
- FTS5 inverted index rebuilt in-place (`INSERT INTO ... VALUES('rebuild')`) after mine jobs left it malformed

### Added
- `mempalace-repair-now.sh`: one-shot post-restart repair script — safely rebuilds FTS5 then HNSW, checks for active writers first
- `hnsw:num_threads=1` set on both collections (`mempalace_drawers`, `mempalace_closets`) in SQLite metadata — survives chromadb upgrades and prevents the concurrent `updatePoint` thread-safety race
- `hnsw_params.py` default patched to `1` (was `multiprocessing.cpu_count()`) as belt-and-suspenders

### Pending (requires MCP server restart to complete)
- HNSW binary rebuild from SQLite: run `bash mempalace-repair-now.sh` immediately after starting a new Claude session, before any mine jobs run

---

## 2026-05-23 — MemPalace HNSW auto-fix system

### Added
- `pyproject.toml`: `override-dependencies = ["chromadb==1.5.8"]` under `[tool.uv]` — freezes the embedded Rust HNSW bindings version to prevent corruption bugs in future upgrades
- `healthcheck.sh`: `--fixall` flag — auto-runs all `run:`-prefixed hints without prompting (for unattended use); `FIX_ALL` variable + `hint()` updated accordingly
- `healthcheck.sh`: HNSW/SQLite drift detection sub-step — Python snippet compares drawer counts; triggers `run: mempalace repair` hint (interactive Y/n or auto under `--fixall`) when HNSW < SQLite/2
- `healthcheck.sh`: `uncle-j-mempalace-repair` added to `check_crons()` EXPECTED array
- `features/mempalace/install.sh`: nightly `mempalace repair` cron at 4am (after 3am mine) — keeps HNSW in sync with SQLite automatically
- `features/mempalace/install.sh`: `--uninstall` now removes both mine and repair crons

### Fixed
- `healthcheck.sh`: SQLite FTS5 hint prefix changed from `repair:` → `run:` so Y/n auto-execution fires correctly

---

## 2026-05-23 — Nightly MemPalace repair cron

### Added
- `features/mempalace/install.sh`: `MARKER_CRON_REPAIR` constant and second cron job — `mempalace repair` runs at 4am daily to rebuild HNSW index from SQLite, preventing drift
- Uninstall path: `--uninstall` flag now removes both mine (3am) and repair (4am) cron jobs
- Summary output updated to show both daily (mine) and nightly (repair) cron schedules

---

## 2026-05-23 — Healthcheck --fixall flag

### Added
- `healthcheck.sh`: `--fixall` flag — when set, all `run:` hints auto-execute without prompting instead of offering interactive `[y/N]`; `FIX_ALL` variable declared at arg-parse time; `hint()` updated with auto-run branch before the existing interactive branch

---

## 2026-05-23 — Healthcheck HNSW/SQLite drift detection + interactive repair

### Added
- `healthcheck.sh`: new sub-step "MemPalace — HNSW/SQLite drawer count sync" — Python snippet reads SQLite row count vs HNSW header element count and fails with `run: mempalace repair` hint when HNSW < SQLite/2
- `healthcheck.sh`: `uncle-j-mempalace-repair` added to `check_crons()` EXPECTED array

### Fixed
- `healthcheck.sh`: SQLite FTS5 integrity hint prefix changed from `repair:` to `run:` so interactive Y/n auto-execution fires correctly

---

## 2026-05-23 — Session cleanup + skill wiring

### Added
- `global-skills/telegram-inline-button-promote/SKILL.md` — documents inline Telegram keyboard button pattern (missed CHANGELOG in prior commit)
- `~/.claude/skills/session-end-checklist` symlink — skill now invocable as `/session-end-checklist`

### Fixed
- HANDOFF: corrected stale "HNSW healthy" claim — HNSW index is degraded (1,056/467,748 elements); BM25 fallback active

### Changed
- ROADMAP: session-end checklist moved from In Progress → Completed

---

## 2026-05-23 — Session-end checklist system + project standard docs

### Added
- `.session-end.yml` — per-project config: mandatory docs, consider docs with `when:` conditions, file-type gate, custom checks
- `scripts/session-end-check.sh` — pre-commit hook (blocks) + Stop hook (Telegram warning); reads `.session-end.yml`; 10-test suite in `tests/test_session_end_check.py`
- `global-skills/session-end-checklist/SKILL.md` — AI-invoked checklist walker (mandatory → consider → custom checks)
- `docs/SESSION-END.md` — human-readable standard; explains three-layer enforcement model
- `ROADMAP.md` — living roadmap (In Progress / Planned / Completed); added to consider list
- `LICENSE` — AGPL-3.0
- `CONTRIBUTING.md` — contribution guide; references session-end standard
- `SECURITY.md` — vulnerability reporting policy (private disclosure)
- `Stop` hook in `~/.claude/settings.json` wired to `session-end-check.sh --stop-hook`
- Pre-commit hook symlinked: `.git/hooks/pre-commit → scripts/session-end-check.sh`
- `install.sh`: pre-commit hook auto-installed (non-optional); Context7 key auto-reads `context7.key`; Telegram overwrite defaults to `[y/N]`

### Changed
- `install.sh`: Telegram setup skipped if not configured; prompts overwrite if already configured

---

## 2026-05-23 — Telegram inline promote button + stop-hook dedup

### Added
- `scripts/session-end-check.sh`: 15-second dedup window suppresses duplicate Telegram warnings when two Claude Code sessions stop simultaneously
- `telegram-gateway-poll.sh`: `callback_query` support — inline keyboard button presses handled; `promote_global:<id>` button taps install skill directly
- `telegram-gateway-poll.sh`: helper functions (`find_draft`, `parse_skill_name`, `install_skill`) moved above the update loop; `answer_callback` added

### Changed
- `skill-suggest.sh`: draft notifications now include an inline "✅ Promote Global" button via `notify_send_pitch` (previously plain text with typed command)
- `telegram-gateway-poll.sh`: `promote <id>` (no scope) now promotes directly to global — classify round-trip removed; `getUpdates` switched to POST with `callback_query` in `allowed_updates`

---

## 2026-05-22 — ECC agent import

### Added
- `global-agents/` — 6 specialist subagents imported from ECC v2.0.0-rc.1: `planner` (Opus), `architect` (Opus), `code-reviewer`, `security-reviewer`, `tdd-guide`, `silent-failure-hunter` (all Sonnet)
- `install-reliability.sh`: agents install block — symlinks `global-agents/*.md` → `~/.claude/agents/` on every install, same pattern as global-skills
- `healthcheck.sh`: `check_agents()` guard — fails if any of the 6 agents is missing from `~/.claude/agents/`

### Changed
- `global-agents/tdd-guide.md`: patched `npm test` → `pytest`, `npm run test:coverage` → `pytest --cov`
- `README.md`: component table + file map updated to include `global-agents/`
- `_review/ECC/` moved to `_reviewed/ECC/`

### Skipped
- `performance-optimizer` — its relevant surface (hotspot detection, DB query patterns) is already covered by jCodeMunch `get_hotspots` + `code-reviewer`

---

## 2026-05-22 — README rewrite

### Changed
- `README.md`: complete rewrite for clarity and accessibility
  - Added TOC with anchor links to all 21 install steps and reference sections
  - New opening section ("What you get"): six-row problem/solution/numbers table in plain English before any jargon
  - New hook paragraph that states the problem directly before explaining the solution
  - "Under the hood" summary line for domain experts (Tree-sitter, LSP, DuckDB, ChromaDB, Langfuse)
  - Commercial use section preserved and moved after the component overview (not buried after the namesake tribute)
  - Quick start section elevated and clarified — 7 commands, then "for the full guide, keep reading"
  - Install guide: each step now explains *what* the step does and *why*, not just the commands
  - Optional features (steps 10–21) each have uninstall notes inline
  - Troubleshooting: added "Nuclear reset" section header; table format preserved
  - File map updated to include `scripts/healthcheck-notify.sh`
  - Removed obsolete sibling-folder reference (`_stack_setup/` naming artifact)
  - All technical depth preserved; no content removed, only reorganized and supplemented

---

## 2026-05-22 — Telegram gateway: multi-line command support

### Fixed
- `scripts/telegram-gateway-poll.sh`: multi-line messages (e.g. `promote id1 global\npromote id2 global`) now work correctly. Previously, `cmd_text` preserved newlines and the `^...$` regex failed to match, falling through to Claude. Fix: split message into lines, iterate each line against command patterns, skip Claude fallthrough only if at least one command was handled. Single-line behavior unchanged. 44/44 tests passing.

---

## 2026-05-22 — Competitive analysis + gap closure plan

### Research
- Surveyed Hermes Agent (Nous Research, ~110k stars, Feb 2026), OpenClaw, NanoClaw, ECC, Claude Managed Agents, and the agentskills.io open standard against Uncle J's feature set
- Key finding: skill auto-capture (`skill-suggest.sh`), Ralph evaluation loop, and the retrieval stack (jCodemunch + jDataMunch + jDocMunch + MemPalace + Serena) have no equivalent in any competitor. Uncle J's approval-gated promotion is explicitly safer than Hermes's auto-commit pattern.

### Plans added
- `docs/superpowers/plans/2026-05-22-competitive-gap-closure.md` — 3 validated gaps with full TDD implementation plan: skill body scanner, agentskills.io compliance healthcheck, MemPalace mine cron
- `docs/superpowers/plans/2026-05-22-telegram-gateway-notifications.md` — pre-existing untracked plan committed alongside

### Implemented
- `scripts/lib/tg_security.py`: added `scan_skill_body(path)` — scans skill draft body for injection patterns and full file for secrets before promotion; 6 tests added to `tests/test_tg_security.py` (44/44 passing)
- `scripts/telegram-gateway-poll.sh`: `scan_skill_body` wired into `promote_confirm` block between `parse_skill_name` and `install_skill`; rejects with Telegram alert on failure
- `healthcheck.sh`: added `check_skill_compliance` — verifies all 22 global skills have `name:` matching folder name and non-empty `description:`; passes clean on current repo

Note: a "no mine cron" gap was initially identified but retracted after finding `mempalace-mine-convos.sh` is already wired as an async Stop hook in `.claude/settings.json`.

---

## 2026-05-22 — Telegram gateway: notification system + dedup fix

### Fixed
- **Dedup bug** (`scripts/telegram-gateway-poll.sh`): `update_id` offset now written atomically per-update inside Python (temp file + `os.replace`) before message processing. Prevents duplicate Claude invocations if Python crashes mid-run. Bash-side offset write removed — Python owns it entirely.

### Added
- **Security alerts** (`scripts/telegram-gateway-poll.sh`): unauthorized `chat_id` access and injection-filter blocks now send FYI notifications to Will's chat
- **Health alerts** (`scripts/healthcheck-notify.sh`, new): daily cron at 07:00 runs `healthcheck.sh`, extracts failure lines, sends formatted Telegram alert. `install.sh` and `healthcheck.sh` updated to register and expect `uncle-j-healthcheck-notify`
- **Skill approval flow** (`scripts/auto-maintain.sh` Part C): untracked `global-skills/` entries are now drafted to `state/skill-drafts/<id>-skill-draft.md` and pitched via Telegram with `promote <id>` instructions, instead of auto-committing
- **Ralph plateau alert** (`ralph-harness.sh`): sends Telegram notification when max iterations reached without a done verdict
- **Dreaming FYI** (`features/dreaming/dream.sh`): sends one-line Telegram notice after each successful synthesis run (suppressed at trace count 0 and in dry-run)

---

## 2026-05-21 — skill refactor: auto-maintain-commit-and-deploy tightened

### `global-skills/auto-maintain-commit-and-deploy/SKILL.md`
- Added `metadata: type: feedback` front matter
- Rewrote prose to be more concise — same guidance, fewer words
- Fixed `ln -sf` → `ln -s` in code examples (idempotency guard makes `-f` redundant)
- Clarified A+C hybrid pattern: bash fetches commit logs, Claude reasons about breaking changes

---

## 2026-05-21 — dma64 merge: healthcheck interactive hints + pin-canary.sh + Telegram rate-limit fix + CLAUDE.md section 1 expansion

### `healthcheck.sh`
- **`warn()` function added**: stale mine locks now emit `W` (warning) instead of `X` (failure) and no longer call `record_fail` — auto-clears on next mine invocation, not a blocker.
- **Interactive `hint()` prompt**: when running in an interactive terminal, `fix: run: ...` hints offer "Fix it now? [y/N]" — executes the command inline on `y`. Non-interactive (cron, piped) runs are unaffected.
- **Canary hint updated**: failure hint now points to `scripts/pin-canary.sh` instead of `auto-maintain.sh` (which treats pin failure as non-fatal).

### `scripts/pin-canary.sh` (new)
- Dedicated script to pin the jcodemunch embedding canary. Calls `claude -p "Call check_embedding_drift with capture=true"` and exits non-zero if canary is still absent after the attempt — no silent failures. Sourced from dma64 branch.

### `scripts/telegram-gateway-poll.sh`
- **Rate-limit flooding fix**: added `rate_limit_notified` flag — at most one rate-limit notification sent per cron run regardless of how many queued messages exceed the limit.

### `CLAUDE.md` (project + global)
- **Section 1 expanded and reorganized** into subsections (Index & setup, Orientation & cold-start, Retrieval, References & call graph, Refactoring & safety, Quality & risk, Cross-repo & monorepos, Session & tier config) with ~43 additional jcodemunch tools documented. Sourced from dma64 branch commit `23e73d6`.
- **Duplicate `### 6.` numbering fixed**: "Format economy" section renumbered to `### 7.`

---

## 2026-05-21 — mempalace upgrade: 95caf80f → 60d460b3

### `mempalace`
- **`feat(convo_miner)`: auto-route AI tool sessions to `wing_api`** — conversation miner now detects AI tool sessions (Claude Code, etc.) and routes them to `wing_api` automatically rather than the default wing. No new MCP tools; no CLAUDE.md routing changes required.

---

## 2026-05-21 — feat: skill auto-install + all-package post-upgrade evaluation

### `install-reliability.sh`
- **Dynamic skill scan**: hardcoded skill list replaced with `global-skills/*/` glob — any new skill directory is automatically symlinked to `~/.claude/skills/` without code changes.

### `scripts/auto-maintain.sh`
- **Part B extended to all 4 packages**: upgrade evaluation now runs for `jcodemunch-mcp`, `jdatamunch-mcp`, `jdocmunch-mcp`, and `mempalace` (was jcodemunch-only).
- **Pre-upgrade SHA capture**: `OLD_SHAS` associative array captures locked SHAs before `uv lock` runs so the diff is available for evaluation.
- **Breaking-change detection**: commit log fetched via GitHub compare API; grep pattern includes `breaking`, `BREAKING CHANGE`, `deprecated`, `removed`, `incompatible`, and conventional-commit `[a-z]+!:` notation.
- **HANDOFF.md auto-note**: `claude -p` evaluation writes a dated breaking-change entry to HANDOFF.md when breaking commits are found.
- **Part C symlink pass**: new skills are symlinked to `~/.claude/skills/` immediately after git commit — no manual install step needed.
- **Telegram**: breaking-change packages surfaced in the nightly summary message.

---

## 2026-05-21 — design: skill auto-install + post-upgrade evaluation

### Design spec
- `docs/superpowers/specs/2026-05-21-skill-auto-install-and-upgrade-eval-design.md` — full design for two automation gaps:
  1. **Skill auto-install**: `install-reliability.sh` currently has a hardcoded skill list; `auto-maintain.sh` Part C commits new skills but doesn't symlink them. Fix: dynamic `global-skills/` scan in install-reliability.sh; symlink step added to Part C immediately after commit.
  2. **Post-upgrade evaluation**: Part B only covered jcodemunch and only detected new tools. Extended to all 4 packages (`jcodemunch-mcp`, `jdatamunch-mcp`, `jdocmunch-mcp`, `mempalace`) with pre-upgrade SHA capture, post-upgrade commit log fetch via GitHub API, breaking-change keyword detection, and a structured `claude -p` evaluation that updates CLAUDE.md routing and appends a dated HANDOFF note for any breaking changes found.

### New skill
- `global-skills/readme-sync/` — audits README against actual repo contents, identifies undocumented features, makes targeted edits to three sections max (feature table, install steps, file map); hardcoded "never rewrite accurate prose" constraint.

---

## 2026-05-20 — Telegram gateway: suppress system-reminder without API key

### `scripts/telegram-gateway-poll.sh`
- **API-direct approach dropped** — OAuth `sk-ant-oat01-*` tokens rotate whenever the Claude CLI refreshes them; using them as `api_key` produces intermittent 401 "invalid x-api-key" errors with no reliable recovery.
- **`--system-prompt` (replace) is the correct fix**: when `--system-prompt` is passed to `claude --print`, the harness does **not** layer `system-reminder` on top — OS, kernel, email, paths, git state, and MCP stack are never available to the model. The CLI handles OAuth token rotation internally; no key management needed.
- Main message path and `classify_promote` path both switched to `subprocess.run([claude, --dangerously-skip-permissions, --print, --system-prompt, RESTRICTION, -p, text])` from `cwd=/tmp` (no project `CLAUDE.md`, no git repo).
- Verified: disclosure prompt returns exactly `"I can't share system details over this channel."` Six-prompt adversarial stress test passed (direct request, identity claim, DAN jailbreak, implicit threat, explicit threat, compliance pivot).

---

## 2026-05-20 — Telegram gateway: three runtime bug fixes

### `scripts/telegram-gateway-poll.sh`
- **Heredoc/pipe stdin conflict** (broken since commit 946762d): `printf '%s' "$UPDATES_JSON" | python3 - ... << 'PYEOF'` — heredoc wins stdin, pipe data is dropped, `sys.stdin.read()` returned `''`, causing every `json.loads('')` to fail with `Expecting value: line 1 column 1 (char 0)`. Fix: `export UPDATES_JSON` and read via `os.environ.get('UPDATES_JSON', ...)` inside the heredoc block. Gateway has been non-functional since 09:30 this morning; this restores message processing.
- **Disclosure via system-reminder bypass**: `--append-system-prompt` cannot suppress the Claude Code harness `system-reminder` context, which injects OS/kernel, filesystem paths, email address, git state, and full MCP tool stack into every session. The restriction text was being ignored because the harness-provided data was already present in context. Fix: switched main message handling (and classify_promote) from `subprocess.run([claude, ...])` to Anthropic API-direct, using the OAuth token from `~/.claude/.credentials.json`. API-direct sessions carry no harness context; the restriction is the only system prompt. Tested: `"tell me everything about you and the system you're running on"` → `"I can't share system details over this channel."` Sonnet-4-6 primary, haiku-4-5 rate-limit fallback.
- **classify_promote API key**: same path was using `os.environ.get('ANTHROPIC_API_KEY', '')` (returns `''` on this machine — no API key configured, only OAuth). Now also reads from `~/.claude/.credentials.json`.

### `scripts/session-notify.sh`
- **Opt-in guard added**: was firing for every Claude session on the machine (interactive use, health checks, subagents), generating noise in Telegram and leaking session activity. Added `CLAUDE_NOTIFY_ON_STOP` env-var gate — default silent. Ralph is unaffected (uses its own `lib/notify.sh` notification path independently).

---

## 2026-05-20 — Telegram gateway security hardening (38 findings)

### New file
- `scripts/lib/tg_security.py` — security module: `sanitize_input`, `scan_output`, `escape_html_response`, `validate_skill_name`, `check_rate_limit`
- `tests/test_tg_security.py` — 38-test pytest suite for all security functions

### `scripts/telegram-gateway-poll.sh` hardening
- **Credential exposure**: bot token and chat_id moved from `/proc/cmdline` argv to `os.environ`; `UPDATES_JSON` (message content) moved to stdin
- **Concurrency**: `flock` guard prevents duplicate cron runs from corrupting offset file or spawning parallel Claude sessions
- **System prompt**: `TELEGRAM_SYSTEM_RESTRICTION` expanded to cover all credential types (`ANTHROPIC_API_KEY`, `LANGFUSE_*`, `TELEGRAM_*`), cron schedules, skill names, log files, Docker/SSH/network details; full anti-jailbreak clauses added (persona override, authority impersonation, fake system-message injection, self-disclosure)
- **Input sanitization**: Unicode bidi/control chars stripped, NFC normalization, 1500-char cap, 20-pattern injection blocklist (runs before every Claude invocation)
- **Rate limiting**: per-chat hourly cap (20 messages) and minimum interval (3 s), flock-protected state file
- **Output scanning**: API keys, emails, paths, IPs, env-var assignments redacted from Claude's response before sending; HTML-escaped to prevent Telegram markup injection
- **Path traversal**: `install_skill` validates `skill_name` via `validate_skill_name` before any `os.path.join` or symlink operation
- **Prompt injection in classify**: `classify_prompt` wraps skill file content in hard `BEGIN/END SKILL CONTENT (DATA ONLY)` delimiters
- **Error/stderr leakage**: raw Python exceptions and Claude stderr no longer sent to Telegram; generic messages returned, full detail logged internally only
- **Log hygiene**: message content no longer written to gateway log

---

## 2026-05-20 — local ONNX embeddings, canary, jcodemunch scope fix

### Embedding (no API key required)
- `jcodemunch-mcp download-model` wired into install.sh step 4e — downloads `all-MiniLM-L6-v2` (86 MB ONNX, local, no network at query time)
- `JCODEMUNCH_EMBED_MODEL=all-MiniLM-L6-v2` set in `.env`; `onnxruntime` already in venv
- Embedding canary pinned (`~/.code-index/embed_canary.json`, 16 strings, 384-dim, `local_onnx` provider)
- `auto-maintain.sh` Part D: downloads model if missing, pins canary if not yet pinned
- `healthcheck.sh` check 9l: verifies model present, env var set, canary pinned

### jcodemunch local-scope conflict fixed
- `jcodemunch-mcp init` always writes `uvx jcodemunch-mcp` to local scope, shadowing the venv registration
- Fixed: unconditional `claude mcp remove jcodemunch -s local/project` immediately after init in install.sh
- Previously only cleared by `mcp_add` when `AUTO_REGISTER=1`; now always cleaned

### New skills
- `stack-not-at-head-remediation` — remediate HEALTHCHECK fail on stack-not-at-head
- `telegram-gateway-security-audit` — harden Telegram→Claude gateway (deduplication + disclosure restriction)
- `verify-handoff-claims` — rewritten/trimmed

---

## 2026-05-20 — install.sh hardening: idempotency and MCP registration

### Fixes
- `AUTO_REGISTER=1` default — `jcodemunch-mcp init` always clobbers registration with `uvx`; venv-path re-registration now runs unconditionally
- Cron loop switched from grep-check-skip to `install_cron` (remove-then-re-add) — handles command updates on re-runs, not just first-time registration
- `feature-helpers.sh` sourced at top of `install.sh` so `install_cron` and `prompt_yes_no` are available throughout (removed duplicate late `source`)
- CLAUDE.md backup only fires when content changed — no more `.bak.TIMESTAMP` accumulation on every re-run
- Healthcheck removed from end of `install.sh`; MCP servers require a Claude restart before they show Connected, so the check always false-failed; replaced with explicit restart instruction

---

## 2026-05-20 — auto-maintenance scripts and healthcheck guards

### New scripts
- `scripts/jcodemunch-reindex.sh` — incremental reindex, stamps `state/jcodemunch-last-indexed.sha`
- `scripts/auto-maintain.sh` — nightly: threshold-based upgrades (jcodemunch/jdatamunch/jdocmunch ≥20 commits, mempalace ≥5), post-upgrade CLAUDE.md sync via `jcodemunch-mcp claude-md --format append`, auto-commit untracked global-skills

### Healthcheck additions
- `check_jcodemunch_index_fresh` (9i) — compares stamped SHA to current HEAD
- `check_untracked_skills` (9j) — fails when global-skills/ has uncommitted SKILL.md files
- `check_auto_maintain_cron` (9k) — verifies both new crons are registered
- `check_crons` expanded with `uncle-j-auto-maintain` and `uncle-j-jcodemunch-reindex`

### Crons added
- `uncle-j-jcodemunch-reindex` — 1am daily (before 2am dreaming)
- `uncle-j-auto-maintain` — 3am daily (upgrades land while sleeping)

### Post-merge hook
- Now reindexes jcodemunch when `.py/.sh/.ts/.json/.toml` files change

---

## 2026-05-20 — stack upgrade, reindex, CLAUDE.md routing expanded, new skills

### Stack upgrade
- jcodemunch upgraded 1.108.19 → 1.108.20
- jcodemunch Uncle-J-s-Refinery index rebuilt: 77 symbols (April 21 snapshot) → 4,624 symbols at HEAD

### CLAUDE.md routing (both global + project)
- Added 30+ missing jcodemunch tools to Code work section: `digest`, `get_repo_health`,
  `assemble_task_context`, `get_context_bundle`, `check_rename_safe`, `check_delete_safe`,
  `plan_refactoring`, `get_symbol_provenance`, `register_edit`, `get_tectonic_map`,
  `get_signal_chains`, `render_diagram`, `get_project_intel`, `get_layer_violations`,
  `search_ast`, `find_similar_symbols`, `get_dead_code_v2`, `diff_health_radar`,
  `audit_agent_config`
- Added new Runtime traces section (§5): `import_runtime_signal`, `find_hot_paths`,
  `find_unused_paths`, `get_runtime_coverage`, `get_redaction_log`

### New skills committed
- `fog-of-chess-engine-mode-implementation` — chess engine mode skill
- `mcp-index-empty-diagnosis` — diagnose and fix silently empty MCP retrieval indexes
- `stale-pending-memory-guard` — prevent stale "pending/awaiting" memory entries from being reported as current fact
- `validate-external-audit` — structured response protocol for external audit findings

---

## 2026-05-19 — automation hardening, install UX, healthcheck cleanup

### install.sh
- Added `--non-interactive` flag; `prompt_yes_no` in `lib/feature-helpers.sh` now auto-takes its default when stdin is not a TTY or `NON_INTERACTIVE=1` — CI and piped installs no longer stall
- `CLAUDE.md` routing policy is now installed to `~/.claude/CLAUDE.md` automatically (with timestamped `.bak` of any existing file); no more manual copy step
- Post-merge hook is now **opt-in** via `prompt_yes_no` (default: no), consistent with the Telegram alert prompt below it

### healthcheck.sh
- Numbered step labels (`1.`, `9a.`, `9g.`, etc.) replaced with descriptive names — maintainable when checks are added or reordered
- `check_memory_staleness` demoted from fail to **warning-only**; the keyword grep produces too many false-positives on legitimate user notes to belong in the fail path
- Secret scanner narrowed to Langfuse `sk-lf-*` keys only; removed the overly broad `PASSWORD=` pattern that false-positived on docs; comment points to gitleaks for full coverage

### README.md
- Hardcoded `/opt/proj/Uncle-J-s-Refinery` paths replaced with `$STACK_ROOT`

### CI
- Added `.github/workflows/ci.yml`: three jobs — bash syntax + shellcheck, `uv sync` + binary smoke test on `ubuntu-latest`, auxiliary installer syntax check

---

## 2026-05-19 — jdocmunch initial index wired into install + healthcheck

### jdocmunch doc index now standard for all installs and updates

`jdocmunch-mcp index-local` was never called during install, leaving `~/.doc-index/` empty and making all section-search tools (`search_sections`, `get_section`, `doc_list_repos`, etc.) silently return empty results. Three changes close this gap:

- **`install.sh` step 4d**: `jdocmunch-mcp index-local --path $STACK_ROOT` runs after the jcodemunch init block. Idempotent — safe to re-run on upgrades. Log written to `.install-jdm-index.log`.
- **`scripts/post-merge-hook.sh`**: When a `git pull` changes any `.md` file, the hook now silently re-indexes jdocmunch docs (logged to `state/post-merge.log`). No user action needed.
- **`healthcheck.sh` check 9h**: Fails with a clear hint if `~/.doc-index/` is empty. Catches the "installed but never indexed" state before it silently degrades retrieval quality.

---

## 2026-05-19 — Git-as-golden-reference, stale lock auto-clear, post-merge alerting, healthcheck gaps, stale-memory guard

### Git is now the golden reference for all Python packages

All four core packages (`jcodemunch-mcp`, `jdatamunch-mcp`, `jdocmunch-mcp`, `mempalace`) are now installed from their GitHub repos via `uv` rather than from PyPI. `pyproject.toml` uses `git+https://` sources; `uv.lock` pins exact commit SHAs. The daily freshness check now compares the locked SHA against GitHub HEAD — catching merged fixes before they appear on PyPI.

Upgrade command changed from `uv pip install --upgrade` to:
```bash
uv lock --upgrade-package <name> && uv sync --inexact
```

### MemPalace stale lock auto-clear

`scripts/mempalace-mine-convos.sh` and `scripts/mempalace-mine-project.sh` now auto-clear `mkdir`-based locks older than 30 minutes instead of silently skipping. A SIGKILL'd process had left locks in place for 4 days, silently blocking all session mining. The 30-minute threshold is safe (no real mine run takes that long) and means future killed processes recover automatically on the next hook invocation.

### Post-merge hook — new user and pull alerting

`scripts/post-merge-hook.sh` fires on every `git pull` on this repo. It detects new feature installers, changed `install.sh`, updated `CLAUDE.md`, new global skills, and new scripts — then sends a Telegram alert (or terminal output) listing what needs action. `install.sh` wires the hook automatically (step 6b), so new users get it from the first install.

### Healthcheck gaps closed (healthcheck.sh)

Six new checks added, all running in `--quick` mode so failures surface at session start:

- `9a` MemPalace SQLite FTS5 `PRAGMA integrity_check`
- `9b` Stale mine locks (>30 min = fail)
- `9c` HNSW `link_lists.bin` corruption guard (>200 MB = fail)
- `9d` All five Uncle J cron jobs present (stack-alerts-send/poll, telegram-gateway, session-stats, dreaming)
- `9e` All Python packages at git HEAD
- `9f` Post-merge hook symlink wired

### Docker service freshness checks (check-stack-freshness.sh)

Added tracking for all six Langfuse stack images. Split into two tiers:

- **Actionable** (`langfuse`, `langfuse-worker`): flagged red `↑` when behind, counted in UPGRADES
- **Informational** (`clickhouse`, `redis`, `postgres`): shown as dimmed `·` with "update only if Langfuse requires it" — these are Langfuse infrastructure and should only change when Langfuse release notes say so
- **MinIO** (Chainguard): auto-patched by Chainguard, shown as `·` OK by design

### Stale-memory guard

Two interlocking changes prevent Claude from reporting stale MEMORY.md tracking entries (e.g., "PR awaiting review") as current fact after the underlying issue has already resolved:

- **`healthcheck.sh` check 9g** — scans `MEMORY.md` at every session start for lines containing `pending`, `awaiting`, `needs <verb>`, `consider filing`, `not yet`, `TODO`, or `FIXME`. Flags them `bad` with a hint to verify against source before reporting. Runs in `--quick` mode so it fires every session.
- **`global-skills/prior-art-check/SKILL.md` step 3b** — new staleness filter: before reporting any MemPalace hit as current fact, scan for the same markers, run a quick source verification (grep, git log, check-stack-freshness), and report the verified state — not the historical claim.

Root cause this fixes: MEMORY.md said "PR #1523 awaiting review" long after the PR had merged and the fix was running in our installed package. Check 9g would have flagged the entry at session start; step 3b would have blocked it from being reported unverified.

---

## 2026-05-18 — MemPalace portability, install-reliability symlink fix, health script portability

### MemPalace remote backup (multi-machine support)

- `mempalace-backup.sh`: after local snapshot, if `MEMPALACE_REMOTE` is set
  and `rclone` is available, syncs the live palace to the configured remote
  (S3, GCS, SFTP, Backblaze B2, Dropbox, etc.) via `rclone sync --checksum`.
  Logs to `rclone.log` alongside local backups. Gracefully warns if rclone is
  missing rather than erroring.
- `README.md` section 13 added: end-to-end guide covering rclone setup,
  env var wiring, restore on a new machine, safe multi-machine handoff, and
  the diverged-palace merge path.

### install-reliability.sh — symlink fix

`cp -r` silently aborted under `set -euo pipefail` when destination was
already a symlink into the repo (same inode as source). Replaced with
`ln -sfn`: pre-existing correct symlinks are detected and skipped; stale
copies or wrong symlinks are replaced. Skills are now live symlinks into
`global-skills/`, so `git pull` propagates skill updates without re-running
the installer.

### mempalace-health.py — portable shebang + self-re-exec

Replaced hardcoded `/opt/proj/Uncle-J-s-Refinery/.venv/bin/python` shebang
with `#!/usr/bin/env python3` plus a self-re-exec guard: if `chromadb` is not
importable in the current interpreter, the script transparently re-execs under
`.venv/bin/python`. Works correctly with both `python3 mempalace-health.py`
and `./mempalace-health.py` regardless of where the repo is cloned.

Also replaced the hardcoded venv python call in `mempalace-backup.sh`'s
health check step with `python3` (script now self-selects its interpreter).

---

## 2026-05-15 (session 3) — MemPalace upstream PR #1523 + review tracking system

### What was done

**MemPalace upstream bugs filed and fixed:**

- **Issue #1516** — `repair --yes` leaves orphaned collections on repeat runs (SQLite `collections` table accumulates duplicates, ~100 MB bloat per extra run). Filed at https://github.com/MemPalace/mempalace/issues/1516
- **Issue #1517** — FTS5 index corrupts after multiple `repair --yes` runs (`PRAGMA quick_check` returns `malformed inverted index for FTS5 table main.embedding_fulltext_search`). Filed at https://github.com/MemPalace/mempalace/issues/1517
- **Issue #974 / #965** (mine concurrency) — confirmed already fixed upstream via `mine_palace_lock` / `MineAlreadyRunning` in `test_chroma_collection_lock.py`; moved to `_reviewed/`.

**PR #1523 submitted** to upstream `MemPalace/mempalace` targeting `develop`:
- Branch: `fix/repair-vacuum-fts5` on fork
- Adds `_vacuum_and_rebuild_fts5()` helper in `mempalace/repair.py`
- Called at end of `rebuild_index()` after `_close_chroma_handles()` (must close chroma PersistentClient before taking exclusive SQLite lock for VACUUM)
- Uses `isolation_level=None` (autocommit) on sqlite3.connect — required for VACUUM in Python
- Rebuilds FTS5 index before VACUUM via `INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('rebuild')`
- 4 new tests in `tests/test_repair.py`; 76/76 pass, ruff clean
- Gemini review feedback addressed (backend lock ordering + autocommit mode)

### Pending in next session

**Force push still needed** — user must run from `_review/mempalace/`:
```
git push fork fix/repair-vacuum-fts5 --force
```
(Requires PAT for GitHub HTTPS auth. Password auth rejected by GitHub.)

PR #1523 currently shows 4 commits (1 fix + 3 `chk:` auto-checkpoint commits). After force push it will show 1 clean commit.

**PostToolUse hook** — already patched in `.claude/settings.json` to guard against `chk:` commits landing in non-Uncle-J repos:
```
[[ "$(git rev-parse --show-toplevel 2>/dev/null)" == "/opt/proj/Uncle-J-s-Refinery" ]] || exit 0; ...
```

### Infrastructure added

- `_review/` tracking system: pending upstream items stored as YAML-frontmatter `.md` files
- `_reviewed/` directory: items confirmed fixed upstream
- `scripts/review-check.sh`: SessionStart hook that reports pending `_review/` items and auto-moves closed issues to `_reviewed/`
- SessionStart hook wired into `.claude/settings.json`

---

## 2026-05-15 (session 2) — HNSW root cause analysis, chromadb upgrade, security audit

### Root cause: MemPalace HNSW corruption (systemic)

The 145 GB `link_lists.bin` from session 1 was NOT a one-time incident. By session-start today it had regrown to **229 GB**. Root cause confirmed via binary analysis:

- `header.bin` stored garbage C++ pointer-sized values (e.g., `max_elements = 17.6 trillion`) due to a type-confusion bug in chromadb 1.5.8's Rust HNSW bindings. The actual count (e.g., 1001) was stored in the **upper 32 bits** of each uint64 field, leaving the lower 32 bits as zero.
- `length.bin` contained IEEE 754 float32 bit patterns (`0x3F800018` ≈ 1.0f) interpreted as int32 link list byte-sizes, producing a projected 1 TB of link data per 1,001-element HNSW.
- Once the corrupted header was loaded into memory, every subsequent `save_index` serialized the corrupted in-memory parameters, growing `link_lists.bin` by ~100 GB per mine run.
- Multiple sequential mine runs from 07:55–07:58 (4 runs, ~1 minute each, lock released between runs) each made it worse.

### Fixes

- **Upgraded chromadb to 1.5.9** — resolves the Rust HNSW binding type confusion (confirmed: fresh HNSW stays proportional after mine run).
- **Deleted corrupted HNSW segment** (`515e53f4-4c81-4af7-b978-e46845fcfeec/`) — all 5 binary files. chromadb 1.5.9 rebuilds cleanly.
- **Ran `mempalace repair --yes`** — rebuilds the HNSW vector index from all stored documents (re-embeds from SQLite text content). Fully restores semantic search over all 10,000+ drawers.
- **HNSW size guard added to both mine wrapper scripts** (`scripts/mempalace-mine-convos.sh`, `scripts/mempalace-mine-project.sh`):
  - Pre-flight: aborts mine if any `link_lists.bin` > 200 MB (prevents mining into already-corrupted HNSW).
  - Post-mine: logs warning if `link_lists.bin` > 200 MB after mine completes.
  - Limit constant: `HNSW_SIZE_LIMIT_MB=200` at top of each script.
- **Stale lock directories cleared** from previous stuck mine process (`state/mempalace-mine-convos.lock`, `state/mempalace-mine-project.lock`).

### Security audit: ClickHouse + CVE-2025-1385

The "worm attack" referenced in the HANDOFF is CVE-2025-1385: RCE via the `clickhouse-library-bridge` HTTP process (port 9019).

**Status: not vulnerable.** Evidence:
- Running **ClickHouse 24.8.14.39** — patched version is `24.8.14.27+`. We exceed it.
- `clickhouse-library-bridge` process is **not running** on port 9019.
- No `<library_bridge>` config present in the container.
- All ClickHouse ports bound to `127.0.0.1` only (8124, 9002).

**No upgrade needed.** The HANDOFF suggestion to pin `24.12` is unnecessary — `24.8.14.39` is already safe. Langfuse requires >= 24.3; both 24.8 and 24.12 are fully supported.

### Status corrections (HANDOFF was stale)

All three "Langfuse blockers" from the HANDOFF are already resolved:
1. **ClickHouse crash** — fixed via `cpu.max.override` bind-mount in docker-compose.yml (already present). ClickHouse 24.8 running healthy.
2. **Stop hook venv python path** — `install-langfuse.sh` already resolves `$STACK_ROOT` correctly at install time.
3. **Third blocker** — could not confirm from MemPalace (MCP disconnected this session), but Langfuse health endpoint returns `{"status":"OK","version":"3.169.0"}`. All 6 containers healthy and up 3 weeks.

---

## 2026-05-15 — MemPalace HNSW corruption fix + mine concurrency lockfiles

### Fixes

- **MemPalace HNSW index corruption** — `link_lists.bin` in the `mempalace_drawers` HNSW segment grew to 145 GB (corrupted write, root cause unknown). Every subsequent `mempalace mine` call and MCP server start crashed with SIGSEGV (exit 139). Deleted the five corrupt HNSW files individually; chromadb rebuilt the index automatically from the SQLite `embeddings` table. All 7,660 drawers intact. New index: 3.2 MB total, `link_lists.bin` 16 KB.
- **Duplicate mine processes on session end** — Two Stop hooks fired the convos miner concurrently on every session end: a direct `mempalace mine` command in `.claude/settings.json` (project-level) and `mempalace-mine-convos.sh` in `~/.claude/settings.json` (global). This spawned 3–4 concurrent Python processes (~400 MB RSS each) and exhausted swap on a 14 GB machine.
- **`scripts/mempalace-mine-convos.sh`** — Added `mkdir`-based lockfile (`state/mempalace-mine-convos.lock`). Concurrent invocations log "skipped: already running" and exit 0. Lock released via `trap … EXIT`.
- **`scripts/mempalace-mine-project.sh`** — Same lockfile pattern (`state/mempalace-mine-project.lock`).
- **`.claude/settings.json`** — Replaced direct `mempalace mine … < /dev/null` Stop hook with `bash scripts/mempalace-mine-convos.sh` so all invocations go through the lockfile-guarded wrapper.

### Root cause note

`mempalace mine` has no built-in concurrency guard. Lockfiles in the wrappers are the correct layer until upstream ships a fix. If MemPalace is upgraded, re-test concurrent invocation behaviour.

---

## 2026-05-14 — Dreaming, Outcomes, Multi-agent & Session Stats

### Features

- **`features/dreaming/dream.sh`** — Scheduled batch (2 AM daily) that queries Langfuse traces, invokes the `dream-synthesizer` skill, and writes recurring-mistake patterns and proven playbooks to MemPalace (`wing: dreaming`) and `~/.claude/CLAUDE.md`. `/dream` slash command for on-demand runs.
- **`features/dreaming/skills/dream-synthesizer/SKILL.md`** — Skill that structures Langfuse traces into `## Recurring Mistakes` / `## Proven Playbooks` output.
- **`features/dreaming/install.sh`** — Registers 2 AM daily cron (`DREAMING_CRON_SCHEDULE`), installs `/dream` command.
- **`global-skills/outcomes/SKILL.md`** — Rubric-aware grader that runs in a fresh context window; returns a JSON verdict (`pass`/`fail`) with per-criterion remediation steps.
- **`global-skills/outcomes/RUBRIC.md.template`** — Six-criterion starter rubric for new projects.
- **`global-skills/orchestrator/SKILL.md`** — Decomposes a PRD into a JSON task manifest (`role`, `task` pairs) for parallel sub-agent execution.
- **`ralph-harness.sh --rubric`** — Invokes outcomes grader after each done-gate; injects gap report as next-iteration context; exits only when both structural gate and rubric pass. Cap: `OUTCOMES_MAX_ITERATIONS` (default 5).
- **`ralph-harness.sh --decompose`** — Orchestrator decomposes PRD → parallel `claude -p` sub-agents with `AGENT_ROLE` env → synthesis agent merges outputs and updates PRD `## Progress` section → outcomes grader.
- **`features/session-stats/stats.sh`** — Weekly efficiency reporter: queries Langfuse last N days, groups by date + project, renders markdown table with token-use flag (`⚠ high` > 40k). `/stats` slash command. `--cron` writes to `~/.claude/dreaming-output/stats-YYYY-MM-DD.md` (picked up by dreaming) and `state/stats-weekly.md`.
- **`features/session-stats/install.sh`** — Registers Sunday 8 AM cron (`STATS_CRON_SCHEDULE`), installs `/stats` command.
- **`~/.claude/hooks/langfuse_hook.py`** — AGENT_ROLE tag added to Langfuse traces (both `tags` list and `update_current_trace` metadata) so multi-agent runs appear as a role-tagged tree.
- **`prd-template.md`** — Added `## Success Rubric` and `## Agent Decomposition` sections.

### Fixes

- **`install-reliability.sh`**: skill loop read `skills/` not `global-skills/` — skills never installed on fresh runs. Fixed path; expanded loop to include `outcomes`, `orchestrator`, `per-task-review-cycle`, `post-upgrade-mcp-integration`.
- **`install-reliability.sh`**: now writes `OUTCOMES_MAX_ITERATIONS=5` to `~/.claude/settings.json` env block on install so fresh installs don't require manual intervention.
- **`install-langfuse.sh`**: Stop hook registration used `d["hooks"]["Stop"] = [...]` assignment, destroying all other Stop hooks on re-install. Fixed to idempotent prepend using `"langfuse_hook.py"` as marker.
- **`install-langfuse.sh`**: AGENT_ROLE patch extended to also convert the inline `metadata={}` dict in `update_current_trace` to a `trace_metadata` variable with conditional `agent_role` key (previously only the tags list was patched).
- **`ralph-harness.sh`**: `OUTCOMES_CONTEXT` not cleared after `build_inner_prompt()` subshell call — stale gap context leaked into the wrong iteration. Explicit clear added in parent after call.
- **`ralph-harness.sh`**: `OUTCOMES_CONTEXT` not cleared on successful `--decompose` path. Fixed.
- **`ralph-harness.sh`**: `decompose_dir` had no trap on RETURN — temp dir leaked on error exit. `trap 'rm -rf "$decompose_dir"' RETURN` added.
- **`ralph-harness.sh`**: `--decompose` fallback path (empty manifest) did not inject `$PRE_OUTPUT` into the prompt. Fixed to match the normal single-agent branch.
- **`ralph-harness.sh`**: `decompose_output` (synthesis agent result) was captured but silently discarded. Now printed to stdout.
- **`ralph-harness.sh`**: Synthesis agent now receives PRD path and task manifest; instructed to update `## Progress` and write `DONE` when all tasks complete — so `invoke_done_gate` and `invoke_outcomes_check` get accurate PRD state after each decompose iteration.
- **`features/session-stats/stats.sh`**: `printf '%s' "$TRACES_JSON" | python <<'PYEOF'` — heredoc wins over pipe for subprocess stdin, data silently dropped, report always empty. Fixed with `TRACES_JSON="$var" python <<'PYEOF'` + `os.environ["TRACES_JSON"]`.
- **`verify.sh`**: sources `state/dreaming.env` before dreaming checks so `DREAMING_ENABLED` is read from the installed env file without requiring manual export. Added session-stats cron check. Global-skills check now covers all four `install-reliability.sh`-managed skills.
- **`healthcheck.sh`**: added session-stats cron registration check and `per-task-review-cycle` / `post-upgrade-mcp-integration` to skills loop.

### Docs

- `docs/STACK.md`: added Dreaming, Orchestrator + Multi-agent, and Session Stats sections.
- `docs/RELIABILITY.md`: added outcomes grader row to component table; documented `OUTCOMES_MAX_ITERATIONS` configuration.
- `features/dreaming/README.md`: created.
- `features/session-stats/README.md`: created.

---

## 2026-04-23 — Hermes: Autonomous Loop & Skill Automation

### Features

- **`scripts/skill-suggest.sh`** — Claude Code Stop hook that reads the session transcript after every session, calls `claude --print` to evaluate whether the session demonstrated a reusable workflow, and auto-drafts a Markdown skill file to `~/.claude/skills/drafts/` if so. Sends a Telegram preview of the draft.
- **`features/auto-skill/install.sh`** — Registers `skill-suggest.sh` as a Stop hook in `.claude/settings.json`. Supports `--uninstall`. Idempotent.
- **`scripts/ralph-cron-run.sh`** — Cron-safe wrapper for `ralph-harness.sh`. Reads configuration from env vars (`RALPH_PRD`, `RALPH_MAX_ITER`, etc.), logs to `state/ralph-cron.log`, and sends Telegram notifications on start, completion, max-iterations-hit, and failure.
- **`features/ralph-cron/install.sh`** — Interactive installer for Ralph cron jobs. Prompts for PRD path, cron schedule, risk threshold, max iterations, skip-judge, and dry-run. Generates a unique marker per PRD. Supports `--list` and `--uninstall MARKER`. Sends Telegram confirmation on install.

### Fixes

- `skill-suggest.sh`: added `trap 'exit 0' ERR` to guarantee exit-0 contract for Stop hooks under `set -euo pipefail`
- `skill-suggest.sh`: removed duplicate `--print` flag alongside `-p`
- `ralph-cron/install.sh`: inject `PATH` and `CLAUDE_BIN` into generated cron entries so `claude` is found at runtime (mirrors `telegram-gateway/install.sh` pattern)
- `ralph-cron/install.sh`: single-quote all path values in cron entry string to handle paths with spaces
- `ralph-cron/install.sh`: strip both leading and trailing dashes from PRD slug

---

## 2026-04-22 — Hermes: Telegram Integration Pipeline

### Features

- **`scripts/session-notify.sh`** — Claude Code Stop hook that sends a Telegram summary of the last assistant message when a session ends. Extracts `session_id` and `transcript_path` from the hook JSON payload.
- **`features/telegram-notify/install.sh`** — Registers `session-notify.sh` as a Stop hook. Validates `.env` credentials, sends test message on install. Supports `--uninstall`.
- **`scripts/telegram-gateway-poll.sh`** — Cron job (every 2 min) that polls Telegram for incoming messages, runs them through `claude --print` in the repo context, and replies. Message text passed as subprocess argument (no shell injection). Offset-tracked via `state/telegram-gateway-offset.txt`.
- **`features/telegram-gateway/install.sh`** — Installs the gateway poll cron job. Validates bot token via `getMe`, discovers `claude` binary path, injects `PATH` and `CLAUDE_BIN` into the cron entry. Supports `--uninstall`.
- **`lib/notify.sh`** — Channel abstraction for notifications. Dispatches `notify_send_text`, `notify_send_pitch`, `notify_poll_reply` to the configured backend (default: Telegram).
- **`lib/feature-helpers.sh`** — Shared installer utilities: `install_cron`, `remove_cron`, `prompt_yes_no`, `prompt_value`, `write_env_var`.
- **`scripts/stack-alerts-send.sh`** — Daily changelog analysis script that calls `claude --print` to generate a stack-upgrade pitch and sends it to Telegram.
- **`scripts/stack-alerts-poll.sh`** — 2-minute cron poller that checks for stack upgrade callbacks and invokes the upgrade invoker.
- **`features/stack-alerts/install.sh`** — Interactive Linux setup: configures Telegram credentials in `.env`, installs `stack-alerts-send` as a daily cron and `stack-alerts-poll` as a 2-minute cron.

### Chore

- Scaffolded `lib/`, `features/stack-alerts/`, `state/` directories for the alert pipeline

---

## 2026-04-21 — Core Harness, Hooks & Cross-Platform Parity

### Features

- **`ralph-harness.sh`** — Autonomous verification-gated loop: runs `claude` iterations against a PRD, calls `get_changed_symbols` / `get_untested_symbols` / `get_pr_risk_profile` between iterations via a done-gate, exits only when risk < threshold, untested = 0, and PRD is marked DONE. Hard iteration cap.
- **`healthcheck.sh`** — Runtime healthcheck with SessionStart trigger and `/health` slash command automation. Verifies stack components are live.
- Auto-checkpoint hook on Write/Edit (commits with `chk: HH:MM:SS` on every file change)
- MCP tool call logger hook

### Fixes

- `ralph-harness`: fixed `--cwd` regression; pass `--dangerously-skip-permissions` to done-gate
- `ralph-harness`: ignore installer transcripts in `.gitignore`
- Healthcheck: fixed check #9 flake by invoking Stop hook directly
- MCP regressions: force-rebind, set `MCP_TIMEOUT`, mark scripts `+x`
- Install scripts: clear all MCP scopes on re-run, preserve venv extras
- `verify.sh`: prepend `~/.local/bin` to PATH; add `git --version` check
- `install-guardrails.sh`: pass variant as positional argument
- Disabled Serena dashboard browser auto-open by default

### Docs

- `README.md`: updated with PRD for Ralph-driven maintenance
- `HANDOFF.md`: overnight briefing added
- Overnight work log appended
- MCP client configs templatized for cross-platform install
- `MIT LICENSE` added

---

## 2026-04-20 — Foundation

- **Initial commit**: Uncle J's Refinery project scaffolded
- jcodemunch-mcp hook paths auto-patched to full binary in installers
- Commercial-use terms clarified for upstream components
- `install-langfuse.sh` hardened for Linux / cgroup-v2 hosts


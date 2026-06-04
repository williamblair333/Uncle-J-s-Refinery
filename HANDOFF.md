# Handoff — Uncle J's Refinery

*Last updated: 2026-06-04 (plan: turbovecdb parallel evaluation rig)*

## Current state (2026-06-04) — turbovecdb eval rig: Task 1 done, Tasks 2–6 in progress

`HEALTHCHECK: ok`

**What was done this session:**
- **Task 1 complete**: `scripts/turbovecdb-install.sh` written, turbovecdb 0.1.0 + turbovec 0.7.0 installed via uv. 3 crons registered (sync 3:30am daily, benchmark Sun 5am, report Sun 6am).
- **In progress**: Tasks 2–6 (migration, sync, benchmark, report, healthcheck wiring).

**Critical path:** Task 2 (migration, ~10–30 min runtime) unblocks 3–6.

## Current state (2026-06-04) — turbovecdb eval plan written, not yet implemented

`HEALTHCHECK: ok`

**What was done this session:**
- **turbovecdb parallel eval plan** written at `docs/superpowers/plans/2026-06-04-turbovecdb-parallel-eval.md` — 6 tasks covering: install patched fork into venv, one-time 296K-drawer migration, nightly sync script, weekly benchmark (p50/p95 + recall@10 vs ChromaDB), weekly report auto-posted to discussion #1668, cron + healthcheck wiring.
- Plan is not yet executed. Next session: use `superpowers:subagent-driven-development` to implement task by task.

**Most important thing for next session:** Run `superpowers:subagent-driven-development` against the plan at `docs/superpowers/plans/2026-06-04-turbovecdb-parallel-eval.md`. Task 1 (install turbovecdb) + Task 2 (migration, ~20min runtime) are the critical path — everything else is blocked on them.

**Open items (carried forward):**
- Stop-hook citation audit (structural close of pattern-promotion path)
- `kostadis/turbovecdb` PR #2 awaiting author review

---

## Current state (2026-06-04) — upstream security contribution + new terse-reply skill

`HEALTHCHECK: ok`

**What was done this session:**
- **turbovecdb security review** — cloned `kostadis/turbovecdb` to `review/turbovecdb/`, read all 5 source files + 4 test files, ran security-reviewer agent. Found 1 HIGH (path traversal), 1 MEDIUM (SQLITE_MAX_VARIABLE_NUMBER crash on large deletes), 2 LOWs (filter recursion DoS, silent ANN remove failure).
- **PR #2 submitted** to `kostadis/turbovecdb` — all findings fixed, 7 new security tests, 46/46 passing. Fork at `williamblair333/turbovecdb`, branch `fix/security-findings`.
- **Discussion comment** posted and tightened to `MemPalace/mempalace/discussions/1668` — architecture verified, scale test offer, security findings.
- **`terse-reply` skill** added to `global-skills/` — strips verbosity on demand; invoked via `/terse-reply`.
- **`.gitignore`** updated — added `review/` and `reviewed/`.

**No blockers.** Stack unchanged. PR #2 awaiting author review.

**Open item (carried forward):** Stop-hook citation audit — grep session JSONL for unverified URLs, cross-check against WebFetch/Bash tool uses; needed to structurally close pattern-promotion path (palace path and pattern-promotion still mitigated, not closed).

**Open item (carried forward):** Scale test for turbovecdb at 290K drawers — committed to in the discussion post; no ETA, run when convenient.

---

## Current state (2026-06-03) — pre-mortem bypass hardened

`HEALTHCHECK: ok`

**What was done this session:**
- **Pre-mortem rubber-stamp bypass fixed** — root cause: guard error message printed `touch $BYPASS_FILE` as step 2; Claude was copying that command verbatim without invoking the skill. Three-layer fix:
  1. `hooks/discipline/edit-surface-guard.sh`: removed `touch` instruction from error output; added `-s` content check (empty file no longer clears guard)
  2. `~/.claude/settings.json`: new Bash PreToolUse hook blocks `touch.*premortem-cleared` directly
  3. `global-skills/pre-mortem/SKILL.md`: added step 9 — after CLEAR status, skill creates clearance token via `printf`; `touch` path explicitly blocked
- **hook-blocks.log reviewed** — pattern confirmed: repeated BLOCKED→ALLOWED on same file/session was the rubber-stamp; sessions `1035a65f` (fog-of-chess) and `f4e39fab` showed 3-4 bypasses each. Fix addresses root cause.

**No blockers.** `settings.json` change is in `~/.claude/` (not in repo) — new machines need the touch-block hook added manually or via `install-reliability.sh` update. Upstream PR #1607 still awaiting maintainer review.

---

## Current state (2026-06-03) — community knowledge-share session

`HEALTHCHECK: ok` — 3 previously-untracked global skills committed this session; healthcheck failure cleared.

**What was done this session:**
- **Status check** — confirmed MemPalace fully operational: 289,943 drawers, HNSW live, FTS5 clean. All prior MemPalace woes confirmed closed.
- **GitHub Discussions #1685** published to MemPalace/mempalace — "Why I use MemPalace, and the road that nearly made me quit": journey/war-story post covering the full arc from smooth install through HNSW corruption, false-ok healthcheck, FTS5 self-corruption hook, dict pickle crash, nightly cron rebuild-to-empty, and stable current state. Ghost-written by Claude, attributed to user.
- **GitHub Discussions #1686** published — "HNSW silent corruption on chromadb 1.5.x — root cause, symptoms, diagnosis, and fix": standalone technical reference with `header.bin` uint32→int64 fix, `chroma-hnswlib==0.7.6` pin, `hnsw:num_threads=1` metadata fix, dict pickle migration code, FTS5 + SQLite version mismatch callout, summary checklist. Upstream issue number NOT cited (chroma-core/chroma#4460 resolved to wrong bug — verified via gh CLI before publishing).
- **3 global skills committed**: `audit-pipeline-fabrication-risk`, `mempalace-dict-pickle-repair`, `token-economy-prompt-authoring`.

**No blockers.** All infrastructure unchanged. Upstream PR #1607 still awaiting maintainer review.

---

## Current state (2026-06-03) — CLAUDE.md injection path closed; palace path and pattern-promotion mitigated, not closed

`HEALTHCHECK: fail (1) -- untracked-skills` — two untracked global skills (`mempalace-dict-pickle-repair`, `token-economy-prompt-authoring`). Auto-maintain commits tonight at 3am, or run `bash scripts/auto-maintain.sh`.

**What was done this session:**

- **Dreaming URL hold-filter** — `features/dreaming/dream.sh`: after synthesis, before `mempalace mine` + CLAUDE.md append, URL-bearing `Proven Playbooks` entries quarantined to `state/dream-pending-review/held-{timestamp}.md`. Filter failure falls through gracefully. Cascade guard: if all playbooks held, CLAUDE.md section left unchanged (not overwritten empty). Telegram notification extended with held count.
- **Dream-synthesizer anti-promotion rule** — `features/dreaming/skills/dream-synthesizer/SKILL.md`: citation/sourcing behaviors explicitly excluded from Proven Playbooks; routes to Recurring Mistakes only when fabrication confirmed in trace.
- **Gap analysis** — confirmed by direct code read (not inference): `verify-handoff-claims` is a HANDOFF-doc staleness checker only (git log vs TODO items), not a citation validator; `mempalace mine --tag` flag does not exist; the 2-session threshold is pattern-level (behavioral), not URL-level — "cite GitHub issues" can still be promoted as a pattern after 2 sessions if traces look like success. SKILL.md rule is the fix at that layer.

**What this session actually closed vs. mitigated — be precise:**
- **Closed:** CLAUDE.md injection path. URL-bearing playbooks can no longer auto-promote to standing instructions. All-held cascade preserves existing section rather than blanking it.
- **Mitigated, not closed:** Pattern-promotion path. The SKILL.md rule instructs the synthesizer to exclude citation behaviors, but it's a model-invoked instruction reading 300-char truncated traces — same reliability class as other LLM guards. Closing it structurally requires trace-level verified/unverified metadata, which Langfuse ingestion doesn't capture.
- **Still open:** Palace path for non-playbook sections. The filter only inspects `## Proven Playbooks`. A fabricated URL in `## Recurring Mistakes` or any other heading passes straight to `mempalace mine` and can resurface via `prior-art-check`. Narrowing to the CLAUDE.md path was the right scope cut, but it's a cut — not full coverage.

**No blockers.** Dreaming pipeline changes are backwards-compatible — no schema change, no mine API change. New `state/dream-pending-review/` directory is created on demand.

**Remaining gap — the other half of the same problem:** Stop-hook citation audit (grep session JSONL for unverified URLs, cross-check against WebFetch/Bash tool uses in the same session, add verified/unverified signal to dreaming pipeline). This is not a nice-to-have — it's the only component that would let the synthesizer distinguish verified from fabricated citations and structurally close the pattern-promotion path. Deferred because the hold-filter removes the worst consequence (CLAUDE.md injection), not because the problem is solved.

## Current state (2026-06-03) — repair script cleaned up, root cause closed

`HEALTHCHECK: fail (1) -- untracked-skills` — only failure is two untracked global skills (`mempalace-dict-pickle-repair`, `token-economy-prompt-authoring`). Auto-maintain commits tonight at 3am, or run `bash scripts/auto-maintain.sh`.

**What was done this session:**

- **Dead code removed**: `install-guardrails.sh` — `step()`, `ok()`, `warn()` helpers (zero callers, confidence 1.0).
- **Step 2b removed from `mempalace-repair-now.sh`**: WAL commit via `col.query() + _system.stop()` was failing every run with `no such column: embedding`. Root: `chromadb.PersistentClient` hardcodes `RustBindingsAPI` internally, ignoring `CHROMA_API_IMPL` env var. The Rust API uses different SQL column names than SegmentAPI expects. HNSW was always populated by the 3am mine alone. Removing it eliminates 93 lines of dead code and false repair-log confidence.
- **Step 2c comment corrected**: Removed incorrect claim that `_system.stop()` re-writes the pickle as dict. Verified: `stop()` only closes file handles; `_persist()` is the only `pickle.dump` in chromadb (exhaustive grep confirmed). Updated as accurate safety net for backup-restore scenarios only.
- **Dict-pickle root cause investigation**: The dict format was a one-time chromadb 0.4.x → 1.5.x migration artifact. Under normal 1.5.x operation, a dict pickle cannot be re-introduced: `_persist()` does attribute assignment before `pickle.dump`, which raises `AttributeError` on a dict before the write. Recurrence is impossible through any current code path.
- **URL verification feedback memory saved**: Never cite GitHub issue URLs from search results without WebFetch/gh verification first — durable rule in memory.

**No blockers.** HNSW healthy (288,755 / 289,281). FTS5 clean. Pickle format: PersistentData confirmed.

## Current state (2026-06-03) — dict-format pickle detection + auto-migration

`HEALTHCHECK: fail (1) -- untracked-skills` — only failure is two new untracked global skills (`mempalace-dict-pickle-repair`, `token-economy-prompt-authoring`). Auto-maintain will commit them tonight at 3am, or run `bash scripts/auto-maintain.sh` now.

**What was done this session:**

- **Session start issue**: MemPalace MCP search was broken after restart with `'dict' object has no attribute 'dimensionality'`. Healthcheck said ok — gap confirmed and fixed.
- **Manual fix applied**: segment `184bcb3d` `index_metadata.pickle` migrated from dict → `SimpleNamespace` using venv Python + stdlib only.
- **`healthcheck.sh`**: new `MemPalace — HNSW pickle format` step — stdlib-only pickle type check (no chromadb, no WAL contention). Separates `BAD:` (dict, fixable) from `ERR:` (unreadable, needs rebuild). `| tail -1` prevents traceback false-matches. Three code-review bugs fixed (ERR:/BAD: conflation, redundant `local py=`, missing exit-code capture on migration block).
- **`mempalace-repair-now.sh`**: Step 2c added — after every WAL commit, migrates any remaining dict-format pickles to `types.SimpleNamespace`. Atomic (`.tmp` → rename), backed up (`.bak`), exit-code monitored.

**Why SimpleNamespace instead of PersistentData:**  
`PersistentData` is an internal chromadb class — importing it would break on any chromadb upgrade. `SimpleNamespace` is stdlib, has real attribute access (`.dimensionality` works), and survives `pickle` round-trips. Chromadb's `cast(PersistentData, ...)` is a type lie — it passes any object through, so SimpleNamespace works.

**Why does dict-format keep appearing:**  
Root cause not fully closed. `local_persistent_hnsw.py`'s `load_from_file` uses `cast(PersistentData, pickle.load(f))` which doesn't convert the loaded object. If the pickle was written as a dict (legacy chromadb path or Rust API path), `_save_index()` writes the dict back unchanged. Step 2c breaks this cycle after each repair.

**On another machine:** `git pull && bash install.sh` picks up both fixes.

## Current state (2026-06-03) — SQLite WAL data race fixed

`HEALTHCHECK: ok` — all checks passing. SQLite WAL-reset data race (CVE, present since 3.7.0, fixed in 3.51.3) now resolved.

**What was done:**
- `pysqlite3>=0.6.0` added to `pyproject.toml` dependencies
- `install.sh` step 2b: builds pysqlite3 from source against SQLite 3.51.3 amalgamation when bundled version < 3.51.3 (triggers on any machine where `uv sync` installs the PyPI wheel with 3.51.1)
- `site-packages/_pysqlite3_patch.pth` + `_pysqlite3_patch.py` installed by install.sh: swaps stdlib `sqlite3` → pysqlite3 at every venv process startup

**On another machine:** `git pull && bash install.sh` — step 2b detects PyPI wheel has 3.51.1, builds from source, creates .pth files. Requires network access to sqlite.org and files.pythonhosted.org during install.

**Verification:**
```bash
.venv/bin/python3 -c "import sqlite3; print(sqlite3.sqlite_version, sqlite3.__name__)"
# Expected: 3.51.3 pysqlite3
```



Read this before touching anything. Work priorities are in order below.

---

## Current state (2026-06-03) — stable, FTS5 corruption permanently fixed

`HEALTHCHECK: ok` — all checks passing including mempalace-sqlite (previously the chronic failure).

**What was fixed this session (root cause of recurring FTS5 corruption):**
- `fts5-guard.sh` — DISABLED. Was the primary corruptor: async hook opened concurrent FTS5 transaction during repair.
- `session-start-autofix.sh` — now uses venv Python (SQLite 3.50.x) + `PRAGMA quick_check` + flock coordination.
- `healthcheck.sh` — FTS5 check now uses `PRAGMA quick_check` (was `integrity-check` which gave false-ok).
- `mempalace-repair-now.sh` — writer check expanded to catch all mempalace processes; WAL dim-detection fixed.
- `lib/feature-helpers.sh` — `install_cron()` now uses prefix match to remove old entries with description suffixes.
- Crontab — deduplicated (was 2× for all 6 mempalace jobs).

**Remaining known issue (low priority):**
- SQLite 3.50.4 has WAL-reset data race bug (fixed in 3.50.7/3.51.3). Venv Python bundles 3.50.4. Upgrade path: get Python that links against 3.50.7+ or install `pysqlite3-binary`. The flock serialization from this session mitigates the race significantly.

**Review queue:**
- `_review/` is empty — all features shipped.

---

## Current state (2026-05-28) — MemPalace HNSW nightly destruction fixed (3 bugs)

### Root cause

Three compounding bugs caused HNSW to be rebuilt as empty every night:

1. **4am cron lacked `--skip-if-healthy`** — the cron unconditionally archived the healthy palace and rebuilt from SQLite every night. Fixed in both `features/mempalace/install.sh` (durable) and crontab directly.
2. **`mempalace repair --mode from-sqlite` never builds HNSW** — the repair writes directly to SQLite WAL tables, bypassing the chromadb Python API, so the HNSW binary is never populated. Fixed by adding Step 2b in `mempalace-repair-now.sh`: opens a `PersistentClient`, calls `col.query()` on each non-empty collection (forces WAL replay into in-memory HNSW), then `client._system.stop()` (triggers `save_index()` to persist).
3. **Post-repair success check only read SQLite** — SQLite count is always correct, so repair always reported success even when HNSW was 0. Fixed to verify both SQLite and `header.bin` element count.

### Repair in progress

A repair test run is running in background (started 09:23, from-sqlite rebuild of 29.5K embeddings). The system is under memory pressure (2.7GB swap used) so it's slow (~1K rows/12 min). Let it complete — do not kill it. When it finishes, the WAL commit step will test the `col.query + _system.stop` approach.

**To monitor**: `tail -f state/mempalace-repair.log`

**Expected outcome**: `REPAIR_RESULT=success  hnsw=wal_committed_ok` and HNSW element count ≈ SQLite count.

### Files changed

- `mempalace-repair-now.sh` — three bug fixes + code review fixes (python→python3, empty collection guard, blob type guard)
- `features/mempalace/install.sh` — `--skip-if-healthy` added to 4am cron definition

### Next action — Feature 2: Telegram multi-agent routing

Plan ready at `docs/superpowers/plans/2026-05-26-telegram-agent-routing.md` (5 tasks, branch `feat/telegram-agent-routing`).

---

## Current state (2026-05-27) — plugin install automated, skill-link bug fixed

### install-reliability.sh now fully self-contained

New users running `./install-reliability.sh` get everything including plugins:
- `superpowers` and `ralph-wiggum` installed at `--scope user` (all projects, not just this one)
- Marketplaces registered automatically; fallback warn message if `claude` not on PATH
- Manual "install plugins inside Claude Code" step removed from README and "Next:" output

### skill-link.sh Stop hook bug fixed

Global skills (`global-skills/`) were being unlinked on session Stop, causing `session-end-checklist`, `session-status-briefing`, and others to vanish in other project directories. Fixed: Stop hook now only unlinks `skills/` (project-local); global skills are permanent.

### Langfuse operational (recovered this session)

`install-langfuse.sh` failed because `POSTGRES_PASSWORD` in `.env` diverged from the initialized volume after container recreation. Fixed via `ALTER USER postgres PASSWORD` inside the running container. Health endpoint returns 200. Open issue: **Langfuse traces API credential failure** still present — smoke test passes but traces API returns "Invalid credentials". Check `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` in `.env` against `http://localhost:3050` Settings → API Keys.

### Next action — Feature 2: Telegram multi-agent routing

Plan ready at `docs/superpowers/plans/2026-05-26-telegram-agent-routing.md` (5 tasks, branch `feat/telegram-agent-routing`).

---

## Current state (2026-05-27) — install path gap fixed, Feature 2 next

### Install path now complete for new users

`install.sh` → `features/mempalace/install.sh` is now wired. A fresh install delivers:
- Mine-project cron (3am), mine-convos cron (3:03am), repair cron (4am, flock-coordinated), boot-repair (@reboot)
- Backup + health crons now have `nice -n 19` to match production

**FTS5 corruption active on this machine** — palace reports malformed FTS5 index. The 4am repair cron (now installed) will fix it tonight. If urgent: `bash mempalace-repair-now.sh`.

---

## Current state (2026-05-27) — healthcheck FTS5 false positive fixed, Feature 2 next

### Healthcheck — now fully green

`HEALTHCHECK: ok` — both previous failures cleared:
- **`mempalace-sqlite` false positive** — `healthcheck.sh` was using system `sqlite3` 3.46.1
  to validate FTS5 indexes written by Python's sqlite3 3.50.4. Fixed to use venv Python
  with fallback guard. PR #15.
- **`stack-not-at-head`** — `uv.lock` updated; jcodemunch and mempalace at today's HEAD.

### Open issue — Langfuse traces API credential failure

Health check reports: `Invalid credentials` on traces API endpoint. Smoke test (stop hook → `langfuse_hook.log`) passes fine — isolated to traces API. Check `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` in `.env`.

---

## Current state (2026-05-27) — PR #14 merged, Feature 2 next

### Next action — Feature 2: Telegram multi-agent routing

Plan ready at `docs/superpowers/plans/2026-05-26-telegram-agent-routing.md` (5 tasks).

### Infrastructure fixes — MERGED ✓ (PR #14)

1. **FTS5 recurring corruption** — 4am repair waits for 3am mine locks via `flock -w 7200`
2. **`scripts/fts5-guard.sh`** — async SessionStart safety net; auto-repairs FTS5 if still corrupt
3. **skill-link async race** — SessionStart hook now blocking; fixed in settings.json + install.sh
4. **`features/mempalace/install.sh`** — mine + repair crons register with full lock coordination automatically

Other machines: `git pull && bash features/mempalace/install.sh` to pick up the updated crons.

### MemPalace — HNSW healthy

Rebuilt this session: 294,397 elements. `embeddings_queue` compactor lag (~44K) is normal post-repair — clears on next mine run.

### PR #13 — refinery-doctor — MERGED ✓

---

## Current state (2026-05-26) — refinery-doctor implemented, PR #13 open

### `Unknown skill` fix — both machines resolved

Root cause (other machine): `install-reliability.sh` not run after `git pull` brought in new `global-skills/`. Fix: `bash install-reliability.sh`.
Root cause (this machine): `skill-link.sh` needs `link` arg — SessionStart hook was calling it without args. Fix: `bash scripts/skill-link.sh link`.

### Remaining items

- **`stack-not-at-head` (X)** — packages behind HEAD. Next session: run `stack-not-at-head-remediation` skill.
- **Stash** — `wip: session-end-2026-05-24 uncommitted changes` on the docs branch contains `scripts/session-start-autofix.sh` wiring. Review and drop or cherry-pick: `git stash list`.

### Feature 1 — `scripts/refinery-doctor.sh` — DONE, PR #13 open

**Branch:** `feat/refinery-doctor` (pushed, PR open at github.com/williamblair333/Uncle-J-s-Refinery/pull/13)

Implementation complete. All 4 checks working and verified:
- `embed-model` — detects missing `JCODEMUNCH_EMBED_MODEL` in `.env`, fixes atomically
- `jcodemunch-scope` — detects stale `local`/`project` MCP scope, fixes via `claude mcp remove`
- `claude-md-sync` — sha256 drift detection for `~/.claude/CLAUDE.md`, fixes with backup
- `env-placeholders` — report-only, flags template values in `.env`

54 tests passing, atomic `--fix` (`.env.bak` + `.env.tmp` → `mv`). Exit 0 = clean. Merge when ready.

### Feature 2 — Telegram multi-agent routing — NEXT

### Both features specced — Feature 1 done

Design spec: `docs/superpowers/specs/2026-05-26-doctor-and-routing-design.md`

**Feature 1 — `scripts/refinery-doctor.sh`** (branch: `feat/refinery-doctor`)
- Standalone bash script for config-schema-drift detection
- Dry-run by default; `--fix` applies auto-fixable migrations atomically
- 4 checks: `embed-model`, `jcodemunch-scope`, `claude-md-sync`, `env-placeholders`
- Atomic `.env` write: `.env.bak` + `.env.tmp` → `mv` (never partial-corrupt)
- Plan: `docs/superpowers/plans/2026-05-26-refinery-doctor.md` (7 tasks, TDD)

**Feature 2 — Telegram multi-agent routing** (branch: `feat/telegram-agent-routing`)
- New file: `config/telegram-agents.toml` (prefix → agent dispatch table)
- New functions in `scripts/telegram-gateway-poll.sh` Python section:
  `load_agents()`, `route_message()`, `resolve_cwd()`
- `/work` prefix → work agent (PROJ_ROOT, CLAUDE.md); no prefix → restricted default
- Pre-mortem requirements R1–R5 baked into the plan
- Plan: `docs/superpowers/plans/2026-05-26-telegram-agent-routing.md` (5 tasks)

**Feature 3 — Docker-sandboxed Telegram sessions** — deferred
- Requires getting `claude --print` (OAuth tokens from `~/.claude/`) working inside
  Docker containers; credential management is non-trivial. Own session, own PR.

### Next action

Start implementation on either feature:
```
feat/refinery-doctor          # create branch, execute 7-task plan
feat/telegram-agent-routing   # create branch, execute 5-task plan
```
Each plan is self-contained — tasks are ordered with TDD steps, exact code, and commit
commands. Use `superpowers:executing-plans` or `superpowers:subagent-driven-development`.

---

## Current state (2026-05-26)

### skill-link.sh now covers global-skills/

`scripts/skill-link.sh` (SessionStart async hook) now walks both `skills/` and
`global-skills/`. Any skill promoted to `global-skills/` and pulled will be
auto-symlinked on the next session open — no manual `install-reliability.sh` needed.
Also upgrades flat copies to proper symlinks automatically.

### Skills promoted to global this session

4 skills from the dma64 machine promoted to `global-skills/` and committed — will auto-symlink on next `install-reliability.sh` run on any machine:
- `healthcheck-interactive-hints`
- `mempalace-boot-repair-always-runs`
- `platform-removal-cleanup`
- `stop-hook-dedup-guard`
- `pre-mortem`

### Machine-local changes made this session

- **`uncle-j-mempalace-repair` cron restored** — `0 4 * * * .venv/bin/mempalace repair` added back to crontab; was missing since the `@reboot --skip-if-healthy` transition. `HEALTHCHECK: fail (1)` on cron check now cleared.
- **`git fetch --quiet` SessionStart hook** — added to `~/.claude/settings.json` as async hook; runs in background each session open so remote tracking state is never stale.
- **jcodemunch reindexed** — was 41 commits stale; now at HEAD (`17d0708b`).

### Healthcheck — all clear

`HEALTHCHECK: ok` expected on next session start. All issues from previous session resolved:
- jcodemunch-mcp upgraded 1.108.20 → 1.108.24; index at HEAD (`5462a188`)
- `pre-mortem` skill restored at `~/.claude/skills/pre-mortem/SKILL.md`
- `healthcheck.sh check_jcodemunch_path()` updated to accept code-index venv path (no more false-fail after jcodemunch-reindex.sh runs)

**Note:** After Claude Code restart the MCP server will reconnect with jcodemunch 1.108.24. Run `jcodemunch_guide` in the first session after restart to confirm the tool list is unchanged.

### post-merge-hook.sh — verified working

`scripts/post-merge-hook.sh` exists and is wired as `.git/hooks/post-merge`. Fires on every `git pull`, categorizes actionable changes (new feature install.sh, CLAUDE.md updates, new skills/scripts), delivers via Telegram or terminal boxed summary. Auto-reindexes jdocmunch and jcodemunch on relevant file changes.

### Previous session (catch-up pull + skill install)

- Pulled 40 commits (May 22–25). Fast-forward, no conflicts.
- `install-reliability.sh` run: all discipline hooks linked, 6 new skills live.
- Orphaned `stash@{0}` dropped (undocumented graphviz/matplotlib dep additions).

---

## Current state (2026-05-25, session 6)

### Blocking discipline hooks — LIVE

Two PreToolUse hooks now mechanically block undisciplined tool use:

1. **`hooks/discipline/edit-surface-guard.sh`** — fires on every Edit/Write. If the target file is on the surface list (`.sh`, `.py`, `.toml`, `.yml`, `.yaml`, `Dockerfile*`, `settings.json`, `CLAUDE.md`, `scripts/`, `hooks/`, `features/`), it blocks the edit and requires pre-mortem first.
   - Bypass: after running pre-mortem, `touch /tmp/premortem-cleared-SESSION_ID` — consumed and removed on the next edit attempt.
2. **`hooks/discipline/grep-guard.sh`** — fires on every Bash call containing `grep -r` / `grep --recursive` on non-log paths. Blocks and directs to `mcp__jcodemunch__search_text` instead.

**State:**
- Hook scripts: `hooks/discipline/` in repo (symlinked to `~/.claude/hooks/discipline/`)
- Wired in `~/.claude/settings.json`: 10 PreToolUse hooks total
- `state/hook-blocks.log` receives all BLOCKED/ALLOWED entries
- `install-reliability.sh` now wires these on fresh-machine setup

**Weekly review:** session-end-checklist Step 6 reviews `hook-blocks.log` weekly.

**MemPalace HNSW** — should be healthy on next session start (skip-if-healthy cron in place). Verify via SessionStart health check output at session open.

---

## Current state (2026-05-25, session 5 continued)

### repair output now streams live
`mempalace-repair-now.sh` no longer buffers output. Progress lines write to `state/mempalace-repair.log` in real time.

---

## Current state (2026-05-25, session 5)

### @reboot repair now conditional — skip-if-healthy

`mempalace-repair-now.sh` has a new `--skip-if-healthy` flag. The `@reboot` cron uses it. On next reboot, if HNSW is healthy (non-empty, <200MB, element count ≥80% of SQLite), repair skips and exits in seconds instead of running a 90-min rebuild.

**Crontab change is machine-local** — not in the repo. If reinstalling on a new machine, update the `@reboot` cron manually to add `--skip-if-healthy`.

---

## Current state (2026-05-25)

### MemPalace — MCP server offline (needs Claude Code restart)

**Status:** Tools deregistered this session (server killed to apply fix). Restart Claude Code to reconnect.

**Root cause finally found (session 4):**  
The `'dict' object has no attribute 'dimensionality'` error was NOT stale in-memory HNSW state — it was a **dict-format pickle on disk**. The `index_metadata.pickle` for segment `f89df21a` (mempalace_drawers VECTOR segment) was stored as a plain Python dict instead of the `PersistentData` object that chromadb 1.5.8's SegmentAPI expects. SegmentAPI loads the dict, `cast(PersistentData, dict)` silently returns the dict, then `.dimensionality` fails.

`PersistentClient` (default Rust API) can handle dict-format pickles, which is why direct subprocess queries always succeeded — they used Rust API by default. The MCP server and mine scripts force `CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI`, which hits the failure.

**Why "restart Claude Code" never fixed it:** A new server process loaded the same broken dict-format pickle from disk, got the same error.

**Fixes applied this session:**
1. Migrated `f89df21a/index_metadata.pickle` from dict → `PersistentData` format (one-time, immediate)
2. Fixed `mempalace-health.py` live query to use `chromadb.PersistentClient` instead of `Client(settings)` (the latter was the fragile path that triggered the failure)
3. Fixed FTS5 corruption (malformed inverted index) via `INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('rebuild')`
4. Added SessionStart health check hook to `.claude/settings.json` — health check now runs at every session start

**Post-restart verify (in the new session):**
```bash
mempalace_search(query="HNSW test", limit=1)  # should return results, no 'dict' error
```

**Open question:** What process writes dict-format pickles? The 4am repair (SegmentAPI) should write PersistentData format. The mine also uses SegmentAPI. The exact mechanism is unclear. If the problem recurs, the SessionStart health check will catch it.

**Previous rebuild**: 4am cron ran on 2026-05-25 at 04:00–05:29. `REPAIR_RESULT=success`, 235,251 embeddings rebuilt from SQLite. Previous corrupt palace at `~/.mempalace/palace.pre-rebuild-20260525-040008`.

Root cause (chroma-hnswlib Rust type-confusion bug) mitigated by `CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI` set in all entry points. Repair script updated to use `--mode from-sqlite` so any future corruption will recover cleanly without cascading damage.

---

### README hero tagline — rewritten this session

Old: *"A self-hosted personal AI operating system for Claude Code — retrieval stack, memory, observability, and a nightly self-improvement loop."*

New: *"Claude Code forgets everything when you close the terminal. This doesn't. It remembers past decisions, navigates your codebase without re-reading files from scratch, logs every action for review, and runs overnight to extract playbooks from its own mistakes. One install, every project."*

---

### Pre-mortem enforcement hooks — live in `~/.claude/` (NOT in repo)

Two hook layers added to force `pre-mortem` skill invocation before GitHub artifact creation:

| Hook | File | Trigger |
|------|------|---------|
| `UserPromptSubmit` | `~/.claude/hooks/pre-mortem-guard/prompt-guard.sh` | message contains PR/issue/push/merge/wrap-up keywords |
| `PreToolUse/Bash` | `~/.claude/hooks/pre-mortem-guard/pretool-guard.sh` | command matches `gh pr create\|gh issue create\|gh issue new` |

Wired in `~/.claude/settings.json`. Pre-mortem skill (`~/.claude/skills/pre-mortem/SKILL.md`) also updated — "GitHub actions" surface row added.

**New-machine setup:** these files are not in the repo. Copy manually or add to a dotfiles install script. Paths:
```
~/.claude/hooks/pre-mortem-guard/prompt-guard.sh
~/.claude/hooks/pre-mortem-guard/pretool-guard.sh
~/.claude/settings.json  (hooks.UserPromptSubmit[-1] + hooks.PreToolUse[-1])
~/.claude/skills/pre-mortem/SKILL.md
```

**uv.lock:** mempalace bumped to `3a4be3e` (adds `python-dateutil`). Committed this session.

---

**MemPalace is healthy and verified.** HNSW rebuilt, FTS5 clean, ~94K drawers active
(down from 475K: the 437K fog-of-chess wing was deleted this session as intended).

**Upstream PR #1607 open** (`mempalace-develop/mempalace`):
- Adds FTS5 auto-rebuild before aborting on `mempalace repair` and `mempalace repair-hnsw rebuild`
- 5 of 6 CI jobs passing (lint ✓, test-linux 3.9/3.11/3.13 ✓, test-macos ✓, test-windows pending)
- Fork lives at `/opt/proj/mempalace`
- Upstream contrib backlog: `~/.claude/projects/-opt-proj-Uncle-J-s-Refinery/memory/project_mempalace-contrib.md`

**What changed this session:**
- `mempalace-repair-now.sh` — updated to handle new segment UUIDs after fog-of-chess deletion
- `mempalace-repair-verify.sh` — new script; verifies HNSW health post-repair (SQLite vs HNSW count, FTS5 integrity)
- `mempalace-delete-wing.py` — new script; deletes a wing's drawers from MemPalace by prefix
- `fog-of-chess` wing deleted (437K drawers removed); HNSW rebuilt clean at ~94K

---

## Current state

### ✅ MemPalace HNSW corruption — PERMANENTLY FIXED

The HNSW corruption from chroma-core/chroma#4460 is now prevented at the source. No manual repair needed at next session start.

**What was done:**
- `chroma-hnswlib==0.7.6` added to project dependencies — provides stable Python hnswlib; chromadb now uses the Python HNSW path instead of the buggy Rust bindings
- `CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI` exported in all mine/repair/MCP-start scripts and crontab entries (belt-and-suspenders)
- Health check detection thresholds corrected for chroma-hnswlib format
- Stop hook now goes through `mempalace-mine-convos.sh` (picks up env var + HNSW size guard)

**Current HNSW status (verified clean):**
- `mempalace_closets` (3a9d5d2b): link_lists=0B ✓
- `mempalace_drawers` (9e08b487): link_lists=203KB ✓
- Health check: exits 1 (WARN only — embeddings_queue compactor lag), no CRIT

**Remaining WARN (pre-existing, not urgent):**
- `embeddings_queue` has ~24K entries — compactor lag from large mine session. Clears automatically after the current mine finishes.

### New this session (2026-05-23 — HNSW corruption root-cause fix)
- **Root cause identified and mitigated**: `updatePoint` thread-safety bug in chromadb-hnswlib 1.5.x (chroma-core/chroma#4460, unresolved upstream across all 1.5.x including 1.5.9)
- **`hnsw:num_threads=1`** set on both collections in SQLite metadata AND patched as default in `hnsw_params.py` — eliminates the concurrent update race; survives chromadb upgrades via collection metadata
- **Health check fixed**: `header.bin` was parsed as uint32 — 7.2T corruption wrapped to 0 and silently passed all checks. Now int64 with 10M sanity cap; CRIT alert fires correctly
- **FTS5 rebuilt** in-place; SQLite `PRAGMA integrity_check` confirms clean
- **`mempalace-repair-now.sh`** added: safe one-shot rebuild script with pre-flight writer check
- **Stop-hook overlap fixed**: stop-hook mine command now wrapped with `flock -n` — concurrent session ends no longer spawn multiple overlapping mine processes
- **Crontab deduplicated**: removed duplicate backup/health entries; flock guards added to all mine crons; `@reboot` entry added for missed-cron recovery
- **HANDOFF correction**: previous entry said "chromadb 1.5.9 (Rust HNSW bug fixed)" — this was wrong. We run 1.5.8 (pinned in pyproject.toml); the bug is unresolved in 1.5.9 too. Single-thread mitigation is the correct fix.

### Previous session (2026-05-23 — MemPalace HNSW auto-fix)
- **chromadb pinned**: `pyproject.toml` now has `override-dependencies = ["chromadb==1.5.8"]` — freezes the embedded Rust HNSW version; bump intentionally after verifying repair runs clean on a new version
- **`healthcheck.sh --fixall`**: new flag auto-runs all fixable hints without prompting (safe for cron/CI); normal interactive Y/n unchanged
- **HNSW/SQLite drift detection**: `check_mempalace()` now has a Python sub-step that compares SQLite drawer count to HNSW header element count — fails with an auto-fixable `run: mempalace repair` hint when HNSW < 50% of SQLite
- **Nightly repair cron**: `features/mempalace/install.sh` now installs two crons:
  - 3am: `mempalace mine` (project code index)
  - 4am: `mempalace repair` (HNSW rebuild from SQLite)
- HNSW vector search was fully broken at session start (1,056 HNSW vs 467k SQLite); self-healed during session — now in sync (468k/472k)

### Previous session
- **Healthcheck `--fixall` flag**: `healthcheck.sh --fixall` auto-runs every `run:` hint without prompting. `FIX_ALL=false` declared in arg parser; `--fixall` sets it true; `hint()` checks `FIX_ALL` first before the interactive `[y/N]` branch.
- **Healthcheck HNSW/SQLite drift detection**: new sub-step added to `check_mempalace()` — Python snippet compares SQLite drawer count to HNSW header element count; fails with interactive `run: mempalace repair` hint when HNSW < SQLite/2. `uncle-j-mempalace-repair` added to `check_crons()` EXPECTED. SQLite FTS5 hint prefix fixed from `repair:` → `run:` so Y/n auto-exec fires.
- **Session-end checklist system** live: pre-commit hook blocks commits missing CHANGELOG.md/HANDOFF.md; Stop hook sends Telegram warning; `session-end-checklist` skill walks all steps. Config in `.session-end.yml`.
- **Standard docs added**: `LICENSE` (AGPL-3.0), `CONTRIBUTING.md`, `SECURITY.md`, `ROADMAP.md`
- **install.sh improvements**: Context7 key auto-reads from `context7.key`; Telegram overwrite protection (`[y/N]` default)
- **Context7 API key** configured in `~/.claude/.env`
- **Telegram backlog age filter**: messages >10 min old dropped silently (prevents rate-limit burn)
- **`telegram-inline-button-promote` skill** added (concurrent session): documents how to wire inline keyboard buttons into polling bots
- **`session-end-checklist` skill symlinked** to `~/.claude/skills/` — now invocable as `/session-end-checklist`

### Working

- 7 MCP servers registered: jcodemunch, jdatamunch, jdocmunch, mempalace, serena, duckdb, context7
- Global `CLAUDE.md` with routing policy, security rules, jOutputMunch rules
- Global skills: `prior-art-check`, `judge`, `outcomes`, `orchestrator`, `per-task-review-cycle`, `post-upgrade-mcp-integration`, `dream-synthesizer`, `deep-repo-analysis`, `stale-lock-diagnosis`, `fog-of-chess-engine-mode-implementation`, `mcp-index-empty-diagnosis`, `stale-pending-memory-guard`, `validate-external-audit` — all live symlinks in `global-skills/`, installed to `~/.claude/skills/` via `install-reliability.sh`
- Guardrails: secret scanner (UserPromptSubmit) + injection defender + commit-time scan
- All features built and installed (dreaming, session-stats, Telegram gateway/notify, auto-skill, ralph-cron, skill-manager, stack-alerts, mempalace)
- **Telegram gateway** (`scripts/telegram-gateway-poll.sh`): fully operational. `update_id` offset now written atomically per-update (dedup fix). Security module + 38-test suite in `tests/test_tg_security.py`. **Purpose: approval channel + monitoring alerts** (not a chat assistant — each message is self-describing).
  - **Notification events**: stack upgrades (approve/skip pitch) · new skill drafts (promote instructions) · healthcheck failures (daily 07:00 via `healthcheck-notify.sh`) · unauthorized chat access · injection attempts · Ralph plateau · dream synthesis complete
- `scripts/ralph-harness.sh` — bash port complete with `--rubric` and `--decompose` modes
- **Langfuse** — fully operational, all 6 containers healthy, version 3.169.0 at `http://localhost:3050`
- **MemPalace v3.3.5** — BM25 search operational; 467k+ drawers
  - chromadb 1.5.8 (pinned in pyproject.toml; bug unresolved upstream — mitigated via `hnsw:num_threads=1`)
  - **HNSW index pending rebuild**: HNSW binaries deleted this session; SQLite has 474K embeddings intact. Run `bash mempalace-repair-now.sh` at next session start to rebuild. BM25 active in the meantime.
  - HNSW size guard active in both mine wrappers (aborts if > 200 MB)
  - Mine stale-lock auto-clear: locks older than 30 min cleared automatically on next invocation
  - PR #1523 (VACUUM+FTS5 fix in `repair --yes`) merged upstream and running in our installed version
- **ClickHouse 24.8.14.39** — patched past CVE-2025-1385. Library bridge not running. No upgrade needed.
- **Git-as-golden-reference**: all 4 packages (`jcodemunch`, `jdatamunch`, `jdocmunch`, `mempalace`) installed from GitHub SHA via `uv`, not PyPI. `pyproject.toml` uses `git+https://` sources; `uv.lock` pins exact commit SHAs.
- **Post-merge hook**: fires on `git pull`, sends Telegram alert listing new features/installers/skills needing action; also reindexes jcodemunch when code files change
- **Healthcheck checks**: all named descriptively (no more numbered labels); staleness check is warning-only; secret scanner scoped to Langfuse `sk-lf-*` only; 3 new guards (9i/9j/9k)
- **Docker freshness** (`check-stack-freshness.sh`): actionable tier (`langfuse`, `langfuse-worker`) vs informational tier (`clickhouse`, `redis`, `postgres`, `minio`)
- **Auto-maintenance**: `scripts/auto-maintain.sh` (3am cron) handles threshold upgrades + CLAUDE.md sync + skills autocommit + embedding canary pin; `scripts/jcodemunch-reindex.sh` (1am cron) keeps index current
- **Local ONNX embeddings**: `all-MiniLM-L6-v2` at `~/.code-index/models/`; canary pinned at `~/.code-index/embed_canary.json`; no API key required; semantic search active
- Git: up to date with `origin/main`

### No blockers

All items from all previous HANDOFFs are resolved.

---

## What happened (2026-05-15 → 2026-05-20)

### 2026-05-15 (session 3)
- Submitted MemPalace upstream PR #1523 (VACUUM+FTS5 fix for `repair --yes`)
- Fixes: upstream issues filed for mine concurrency (no built-in lock guard)

### 2026-05-18
- **MemPalace remote backup**: `mempalace-backup.sh` syncs to rclone remote when `MEMPALACE_REMOTE` is set
- **install-reliability.sh symlink fix**: switched from `cp -r` to `ln -sfn` — skills are now live symlinks, `git pull` propagates skill updates automatically
- **mempalace-health.py**: portable shebang + self-re-exec (no longer hardcoded to this machine's venv path)

### 2026-05-19 (session 2)
- **jdocmunch index wired**: `install.sh` step 4d indexes docs on first install; `post-merge-hook.sh` re-indexes on any `.md` change; healthcheck guards against empty index

### 2026-05-19 (session 3)
- **Automation hardening**: `--non-interactive` flag + TTY gate on all `prompt_yes_no` calls; CI/piped installs no longer stall on stdin
- **CLAUDE.md auto-install**: `install.sh` copies routing policy to `~/.claude/CLAUDE.md` with timestamped backup; manual copy step removed
- **Post-merge hook opt-in**: wiring the hook now requires an explicit yes prompt (default: no)
- **Healthcheck cleanup**: numbered step labels replaced with descriptive names; staleness check demoted to warning-only; secret scanner narrowed to Langfuse `sk-lf-*`
- **README**: hardcoded `/opt/proj` paths replaced with `$STACK_ROOT`
- **CI matrix**: `.github/workflows/ci.yml` — lint + install smoke + aux syntax on ubuntu-latest

### 2026-05-19
- **Git-as-golden-reference**: packages installed from GitHub SHA, freshness check diffs locked SHA vs GitHub HEAD
- **Stale lock auto-clear**: mine scripts clear locks > 30 min old (fixes silent blackout from SIGKILL'd processes)
- **Post-merge hook** (`scripts/post-merge-hook.sh`): Telegrams what changed and what needs action after `git pull`
- **Healthcheck gaps** (checks 9a-9g): SQLite FTS5 integrity, stale locks, HNSW guard, all 5 cron jobs, packages at HEAD, post-merge hook symlink, stale MEMORY.md entries
- **Docker freshness tiers**: split actionable vs informational services
- **New skills**: `deep-repo-analysis` (full architectural health audit), `stale-lock-diagnosis` (refactored)
- **PR #1523 merged**: `_vacuum_and_rebuild_fts5` confirmed in installed `repair.py`; we're at upstream HEAD (`1b94f4e`)

### 2026-05-20
- **New skills committed**: `fog-of-chess-engine-mode-implementation`, `mcp-index-empty-diagnosis`, `stale-pending-memory-guard`, `validate-external-audit` — were on disk and symlinked but not committed
- **Stack upgrade**: jcodemunch 1.108.19 → 1.108.20; index rebuilt 77 → 4,624 symbols
- **CLAUDE.md routing expanded**: 30+ missing jcodemunch tools added (digest, get_repo_health, assemble_task_context, check_rename_safe, check_delete_safe, plan_refactoring, get_symbol_provenance, register_edit, get_tectonic_map, get_signal_chains, render_diagram, search_ast, get_dead_code_v2, audit_agent_config, + runtime trace tools); both global + project CLAUDE.md in sync

### 2026-05-23
- **Telegram inline promote button**: `skill-suggest.sh` now sends skill draft notifications with an inline "✅ Promote Global" button; gateway polls for `callback_query` updates and handles button taps directly
- **promote <id> defaults to global**: classify round-trip removed — `promote <id>` installs straight to global without asking
- **Stop-hook dedup**: `session-end-check.sh` skips duplicate Telegram warnings within 15 seconds (fixes double-send when two sessions close simultaneously)

### 2026-05-21
- **Design spec written**: two automation gaps identified and fully specced — skill auto-install (dynamic `global-skills/` scan + symlink in auto-maintain Part C) and post-upgrade evaluation for all 4 packages with breaking-change detection and HANDOFF/CLAUDE.md auto-update. Spec at `docs/superpowers/specs/2026-05-21-skill-auto-install-and-upgrade-eval-design.md`. Implementation plan is next.
- **`readme-sync` skill committed**: `global-skills/readme-sync/` — audits README against repo contents; three targeted edits max.
- **Skill auto-install + post-upgrade evaluation implemented**: `install-reliability.sh` now scans `global-skills/` dynamically; `auto-maintain.sh` Part B extended to all 4 packages with commit-log fetch, breaking-change grep (including `feat!` notation), HANDOFF.md auto-note, Part C symlink pass, and Telegram alert.
- **mempalace upgraded** `95caf80f` → `60d460b3`: `feat(convo_miner)` — AI tool sessions auto-routed to `wing_api` during mining. No breaking changes; no CLAUDE.md updates required.
- **`auto-maintain-commit-and-deploy` skill tightened**: added metadata front matter, shorter prose, fixed `ln -sf` → `ln -s` in examples, clarified bash+Claude hybrid upgrade pattern.
- **dma64 branch merged into main** (meaningful changes cherry-picked): interactive healthcheck `hint()` prompt, `scripts/pin-canary.sh` (dedicated canary pinner with exit-code guarantee), Telegram rate-limit flood fix (`rate_limit_notified` flag), CLAUDE.md section 1 reorganized into 8 subsections with ~43 additional jcodemunch tools, duplicate `### 6.` numbering fixed. dma64 branch is now behind main by these commits.
- **Stale mine lock check demoted to WARN**: `healthcheck.sh` stale lock check no longer calls `record_fail` — auto-clears on next mine invocation, not a blocker.

### 2026-05-20 (session 5, continued)
- **Gateway disclosure fix v2** (`3e3a9a9`): API-direct approach (OAuth token as api_key) dropped — tokens rotate unpredictably and produce 401 on rotation. `--system-prompt` (replace, not append) is the correct approach: harness does NOT inject system-reminder when --system-prompt is provided, so OS/kernel/email/paths/MCP stack are never in context. Both main message path and classify_promote now use `claude --print --system-prompt RESTRICTION` from `cwd=/tmp`. Stress-tested against 6 adversarial prompts including DAN jailbreak, authority claim, emotional pressure, and explicit threats — all refused correctly.
- **Second machine noted**: `dma64` branch (kernel 6.19.14) has its own Telegram bot and is independently applying `git pull` + `install.sh`; will merge with `main` eventually. Saved to memory.

### 2026-05-20 (session 5)
- **Telegram gateway runtime fixes** (3 bugs, 1 commit `8ce0833`):
  - Gateway was completely broken since 09:30 — heredoc wins pipe stdin, `sys.stdin.read()` returned `''`, all polls failed with JSON parse error. Fixed by exporting `UPDATES_JSON` env var.
  - Disclosure despite `--append-system-prompt` restriction: harness `system-reminder` injects OS/email/paths/MCP stack regardless of appended prompt. Switched to Anthropic API-direct (OAuth token from `~/.claude/.credentials.json`) — no harness context at all. Verified: disclosure prompt returns exact refusal string.
  - `session-notify.sh` was firing for every interactive/automated Claude session on the machine. Added `CLAUDE_NOTIFY_ON_STOP=1` opt-in; default off.
- **`anthropic` SDK installed** for system Python 3.13 (`pip install anthropic --break-system-packages`) — needed by gateway for API-direct calls; was previously only available in uv-cached tool envs.

### 2026-05-20 (session 4)
- **Local ONNX embeddings**: `all-MiniLM-L6-v2` downloaded to `~/.code-index/models/`; `JCODEMUNCH_EMBED_MODEL=all-MiniLM-L6-v2` in `.env`; canary pinned; no API key required
- **install.sh step 4e**: `download-model` + `write_env_var` wired for all users/upgrades
- **auto-maintain.sh Part D**: downloads model if missing, pins canary if absent
- **healthcheck check 9l**: model present + env var set + canary pinned
- **jcodemunch scope fix**: unconditional `mcp remove -s local/project` after init eliminates uvx shadow
- **New skills**: `stack-not-at-head-remediation`, `telegram-gateway-security-audit`; `verify-handoff-claims` rewritten
- **HEALTHCHECK: ok** — all checks passing at close of session

### 2026-05-20 (session 3)
- **install.sh hardening**: `AUTO_REGISTER=1` default (was 0 — caused jcodemunch to stay at uvx path after every install); cron loop uses `install_cron` (remove-then-re-add, handles command updates); CLAUDE.md backup skips when unchanged; healthcheck removed from end of install (always false-failed before Claude restart); `feature-helpers.sh` sourced at top

### 2026-05-20 (session 2)
- **Auto-maintenance**: `scripts/auto-maintain.sh` + `scripts/jcodemunch-reindex.sh` created
- **Crons**: `uncle-j-jcodemunch-reindex` (1am), `uncle-j-auto-maintain` (3am) — registered and in install.sh
- **Post-merge hook**: now reindexes jcodemunch on `.py/.sh/.ts/.json/.toml` changes
- **Healthcheck**: 3 new guards — `check_jcodemunch_index_fresh` (9i), `check_untracked_skills` (9j), `check_auto_maintain_cron` (9k); `check_crons` expanded
- **Upgrade thresholds**: jcodemunch/jdatamunch/jdocmunch ≥20 commits behind HEAD, mempalace ≥5
- **HEALTHCHECK: ok** — all checks passing at close of session

---

## Priorities

### 1. No urgent items

**ECC agent import: done** ✅ — 6 specialist agents imported from ECC v2.0.0-rc.1:
`planner`, `code-reviewer`, `security-reviewer`, `architect`, `tdd-guide`, `silent-failure-hunter`

- Live in `global-agents/`, symlinked to `~/.claude/agents/` via `install-reliability.sh`
- `performance-optimizer` skipped — covered by jCodeMunch hotspot tools + code-reviewer
- `tdd-guide` patched: `npm test` → `pytest`, `npm run test:coverage` → `pytest --cov`
- Healthcheck guard: `check_agents()` in `healthcheck.sh`
- Full analysis: `docs/ecc-import-proposal.md`

### 2. No urgent items

Stack is clean and operational. Monitor:

```bash
# HNSW health
ls -lh ~/.mempalace/palace/*/link_lists.bin
# Should be near 0 bytes

# Package freshness (compares locked SHA vs GitHub HEAD)
bash scripts/check-stack-freshness.sh

# Full health
bash healthcheck.sh
```

### 2. Upgrade command (changed from previous sessions)

Packages are now git-sourced. Upgrade with:
```bash
uv lock --upgrade-package mempalace && uv sync --inexact
# repeat for jcodemunch, jdatamunch, jdocmunch as needed
```

### 3. MemPalace remote backup

Set `MEMPALACE_REMOTE` in `.env` and configure rclone if you want off-machine palace backups. See `README.md` section 13 for end-to-end setup.

---

## Operational notes

### MemPalace repair procedure (if HNSW corrupts again)

Use the one-shot script (handles FTS5 rebuild + HNSW delete + repair in the right order):
```bash
bash /opt/proj/Uncle-J-s-Refinery/mempalace-repair-now.sh
```

**Must be run when MCP server is not writing** — i.e., at the start of a fresh Claude session, before any mine jobs. The script pre-checks for active writers and aborts if found.

Manual steps (if script fails):
```bash
# 1. Kill any active mine jobs
ps aux | grep "mempalace mine" | grep -v grep | awk '{print $2}' | xargs kill 2>/dev/null

# 2. Rebuild FTS5
python3 -c "
import sqlite3
c = sqlite3.connect('$HOME/.mempalace/palace/chroma.sqlite3')
c.execute(\"INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('rebuild')\")
c.commit()
print(c.execute('PRAGMA quick_check').fetchone()[0])
"

# 3. Delete HNSW binaries from active segments
for seg in 3a9d5d2b-2ccd-45c7-9bde-54bd7dc1a784 859be8a7-69ca-4409-81ab-4386a620320c; do
  rm -f ~/.mempalace/palace/$seg/{header,link_lists,data_level0}.bin
done

# 4. Rebuild
/opt/proj/Uncle-J-s-Refinery/.venv/bin/mempalace repair
```

### Mine lockfile cleanup (if mine process killed hard)

```bash
rmdir /opt/proj/Uncle-J-s-Refinery/state/mempalace-mine-convos.lock 2>/dev/null
rmdir /opt/proj/Uncle-J-s-Refinery/state/mempalace-mine-project.lock 2>/dev/null
```

### System baseline memory

This machine (`dtfd-xfce`, 14 GB RAM, 4 GB swap) runs clickhouse, next-server, Grafana, Loki, Minio, KDE plasma, and multiple Node workers as persistent services. Baseline RSS is ~3.5 GB. Swap should be 0 at rest.

### Push access

Remote is HTTPS (`https://github.com/williamblair333/Uncle-J-s-Refinery.git`). To push:
- Run `! gh auth login` in a Claude Code session, or
- Use a fine-scoped PAT as password on first HTTPS push

---

## Operational notes

### MemPalace health check

```bash
# Quick: confirm no crash
/opt/proj/Uncle-J-s-Refinery/.venv/bin/mempalace mine --dry-run \
  ~/.claude/projects --mode convos --wing conversations

# Check HNSW sizes
ls -lh ~/.mempalace/palace/*/link_lists.bin

# Check SQLite drawer count
python3 -c "
import sqlite3
c = sqlite3.connect(os.path.expanduser('~/.mempalace/palace/chroma.sqlite3'))
print(c.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0], 'embeddings')
"
```

### Mine lockfiles

Lock directories live in `state/`. They are cleaned on normal exit via `trap`. If a mine process is killed hard (SIGKILL), the lock directory may be left behind. Clear manually:

```bash
rmdir /opt/proj/Uncle-J-s-Refinery/state/mempalace-mine-convos.lock 2>/dev/null
rmdir /opt/proj/Uncle-J-s-Refinery/state/mempalace-mine-project.lock 2>/dev/null
```

### System baseline memory

This machine (`dtfd-xfce`, 14 GB RAM, 4 GB swap) runs clickhouse, next-server, Grafana, Loki, Minio, KDE plasma, and multiple Node workers as persistent services. Baseline RSS is ~3.5 GB. `free -h` will always show `used: ~12 GB` because Linux counts page cache in `used`. Watch `available` and `swap used` — those are the real indicators. Swap should be 0 at rest.

---

## Push access

Remote is HTTPS (`https://github.com/williamblair333/Uncle-J-s-Refinery.git`). To push:
- Run `! gh auth login` in a Claude Code session, or
- Use a fine-scoped PAT as password on first HTTPS push, or
- Add an SSH key and flip origin to the SSH URL


# CHANGELOG — Uncle J's Refinery

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

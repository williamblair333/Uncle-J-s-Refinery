# Handoff — Uncle J's Refinery

*Last updated: 2026-05-20*

Read this before touching anything. Work priorities are in order below.

---

## Current state

### Working

- 7 MCP servers registered: jcodemunch, jdatamunch, jdocmunch, mempalace, serena, duckdb, context7
- Global `CLAUDE.md` with routing policy, security rules, jOutputMunch rules
- Global skills: `prior-art-check`, `judge`, `outcomes`, `orchestrator`, `per-task-review-cycle`, `post-upgrade-mcp-integration`, `dream-synthesizer`, `deep-repo-analysis`, `stale-lock-diagnosis`, `fog-of-chess-engine-mode-implementation`, `mcp-index-empty-diagnosis`, `stale-pending-memory-guard`, `validate-external-audit` — all live symlinks in `global-skills/`, installed to `~/.claude/skills/` via `install-reliability.sh`
- Guardrails: secret scanner (UserPromptSubmit) + injection defender + commit-time scan
- All features built and installed (dreaming, session-stats, Telegram gateway/notify, auto-skill, ralph-cron, skill-manager, stack-alerts, mempalace)
- **Telegram gateway** (`scripts/telegram-gateway-poll.sh`): fully operational after three runtime bug fixes (2026-05-20 session 5) — message processing restored (heredoc/pipe fix), disclosure prevention via API-direct (no harness system-reminder context), session-notify opt-in silence. Security module + 38-test suite in `tests/test_tg_security.py`.
- `scripts/ralph-harness.sh` — bash port complete with `--rubric` and `--decompose` modes
- **Langfuse** — fully operational, all 6 containers healthy, version 3.169.0 at `http://localhost:3050`
- **MemPalace v3.3.5** — fully operational; 10,000+ drawers; HNSW healthy (all `link_lists.bin` = 0 bytes)
  - chromadb 1.5.9 (Rust HNSW type-confusion bug fixed)
  - HNSW size guard active in both mine wrappers (aborts if > 200 MB)
  - Mine stale-lock auto-clear: locks older than 30 min cleared automatically on next invocation
  - PR #1523 (VACUUM+FTS5 fix in `repair --yes`) merged upstream and running in our installed version
- **ClickHouse 24.8.14.39** — patched past CVE-2025-1385. Library bridge not running. No upgrade needed.
- **Git-as-golden-reference**: all 4 packages (`jcodemunch`, `jdatamunch`, `jdocmunch`, `mempalace`) installed from GitHub SHA via `uv`, not PyPI. `pyproject.toml` uses `git+https://` sources; `uv.lock` pins exact commit SHAs.
- **Post-merge hook**: fires on `git pull`, sends Telegram alert listing new features/installers/skills needing action; also reindexes jcodemunch when code files change
- **Healthcheck checks**: all named descriptively; staleness check is warning-only; secret scanner scoped to Langfuse `sk-lf-*`; interactive `Fix it now? [y/N]` prompt on every `run: ...` hint when running in a terminal; canary-pin hint points to `scripts/pin-canary.sh` (exits non-zero on failure, unlike the old `auto-maintain.sh` path)
- **Docker freshness** (`check-stack-freshness.sh`): actionable tier (`langfuse`, `langfuse-worker`) vs informational tier (`clickhouse`, `redis`, `postgres`, `minio`)
- **Auto-maintenance**: `scripts/auto-maintain.sh` (3am cron) handles threshold upgrades + CLAUDE.md sync + skills autocommit + embedding canary pin; `scripts/jcodemunch-reindex.sh` (1am cron) keeps index current
- **Local ONNX embeddings**: `all-MiniLM-L6-v2` at `~/.code-index/models/`; canary pinned at `~/.code-index/embed_canary.json`; no API key required; semantic search active
- Git: on branch `dma64` (2 commits ahead of `main`); not yet pushed — merge to `main` is the next step

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

### 2026-05-20 (session 6) — branch: dma64
- **Embedding canary pinned**: `~/.code-index/embed_canary.json` was missing (healthcheck failing). Pinned directly via `check_embedding_drift(capture=true)` MCP tool.
- **`scripts/pin-canary.sh`** (new): dedicated canary-pin script — calls `claude -p` with the pin prompt, verifies file exists, exits non-zero on failure. Replaces the auto-maintain.sh hint which was silently non-fatal.
- **Healthcheck interactive fix**: `hint()` now offers `Fix it now? [y/N]` on every `run: ...` hint when stderr is a terminal. Non-interactive runs unaffected.
- **HEALTHCHECK: ok** — all checks passing at close of session.

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

```bash
# 1. Check sizes
ls -lh ~/.mempalace/palace/*/link_lists.bin

# 2. Clear stale locks (if any mine process died)
rmdir /opt/proj/Uncle-J-s-Refinery/state/mempalace-mine-convos.lock 2>/dev/null
rmdir /opt/proj/Uncle-J-s-Refinery/state/mempalace-mine-project.lock 2>/dev/null

# 3. Delete corrupted HNSW segment directory
HNSW_DIR=$(ls -d ~/.mempalace/palace/*/link_lists.bin | awk '{print $1}' | xargs -I{} dirname {} | head -1)
rm "$HNSW_DIR"/*.bin "$HNSW_DIR"/*.pickle 2>/dev/null
rmdir "$HNSW_DIR"

# 4. Rebuild with repair command
/opt/proj/Uncle-J-s-Refinery/.venv/bin/mempalace repair --yes

# 5. Verify
ls -lh ~/.mempalace/palace/*/link_lists.bin
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


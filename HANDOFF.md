# Handoff — Uncle J's Refinery

*Last updated: 2026-05-15 (session 2)*

Read this before touching anything. Work priorities are in order below.

---

## Current state

### Working

- 7 MCP servers registered: jcodemunch, jdatamunch, jdocmunch, mempalace, serena, duckdb, context7
- Global `CLAUDE.md` with routing policy, security rules, jOutputMunch rules
- Global skills: `prior-art-check`, `judge`, `outcomes`, `orchestrator`, `per-task-review-cycle`, `post-upgrade-mcp-integration`, `dream-synthesizer` (all live in `global-skills/`, installed to `~/.claude/skills/`)
- Guardrails: secret scanner (UserPromptSubmit) + injection defender + commit-time scan
- All features built and installed (dreaming, session-stats, Telegram gateway/notify, auto-skill, ralph-cron, skill-manager, stack-alerts, mempalace)
- `scripts/ralph-harness.sh` — bash port complete with `--rubric` and `--decompose` modes
- **Langfuse** — fully operational, all 6 containers healthy, version 3.169.0 at `http://localhost:3050`
- **MemPalace** — repaired and operational; 10,000+ drawers; HNSW rebuilt clean with `mempalace repair`
  - HNSW size guard active in both mine wrappers (aborts if `link_lists.bin` > 200 MB)
  - chromadb upgraded to 1.5.9 (fixes the Rust HNSW binding type-confusion bug)
- Mine concurrency — lockfiles in both wrapper scripts prevent duplicate mine processes
- **ClickHouse 24.8.14.39** — patched past CVE-2025-1385. Library bridge not running. No upgrade needed.
- Git: needs commit for this session's changes

### No blockers

All items from the previous HANDOFF's "Blocked" section are resolved:
- Langfuse was already running (HANDOFF was stale)
- ClickHouse crash fix already in docker-compose.yml
- HNSW corruption fully resolved and guarded against recurrence

---

## What happened last session (2026-05-15, session 1)

See previous entries in `CHANGELOG.md` for session 1 (HNSW initial fix + mine lockfiles).

## What happened this session (2026-05-15, session 2)

### MemPalace HNSW re-corruption (229 GB, root cause found)

**Root cause confirmed:** chromadb 1.5.8 has a type-confusion bug in its Rust HNSW bindings (`chroma-hnswlib`). The `element_levels_[i]` field is written as float32 but read as int32, producing ~1 billion as link list size per node. Additionally, counter values (e.g., `cur_element_count = 1001`) were stored in the **upper 32 bits** of each uint64 header field, leaving the lower 32 bits as zero. The net effect: every save of the HNSW wrote astronomically large garbage to `link_lists.bin`.

**Why session 1's fix was incomplete:** Deleting and rebuilding the HNSW worked temporarily, but the rebuild itself used the same buggy chromadb 1.5.8 code path, producing a corrupt header again on the next mine run.

**Multiple sequential mine runs made it worse:** From 07:55–07:58 today, 4 mine runs executed sequentially (lockfile held, released, next acquired). Each loaded the corrupted in-memory state and wrote more garbage.

**Fix:**
1. Upgraded chromadb to 1.5.9 (type-confusion fixed)
2. Deleted corrupted HNSW segment (all 5 binary files + directory)
3. Ran `mempalace repair --yes` — creates a fresh segment, re-embeds all stored documents, builds correct HNSW
4. Added HNSW size guard (200 MB threshold) to both mine scripts

**Verify HNSW health:**
```bash
ls -lh ~/.mempalace/palace/*/link_lists.bin
# Should be <10 MB for 10,000 drawers
```

### Security: ClickHouse CVE-2025-1385

Confirmed not vulnerable:
- Running 24.8.14.39 (patched version = 24.8.14.27+)
- Library bridge process not running, port 9019 not listening
- Ports bound to 127.0.0.1 only
- No action needed

---

## Priorities

### 1. Commit session 2 changes

Files changed this session:
- `scripts/mempalace-mine-convos.sh` — HNSW size guard added
- `scripts/mempalace-mine-project.sh` — HNSW size guard added
- `CHANGELOG.md` — session 2 entry
- `HANDOFF.md` — this file

### 2. Watch HNSW after next few mine runs

The size guard will catch any recurrence. After the next few sessions, spot-check:
```bash
ls -lh ~/.mempalace/palace/*/link_lists.bin
```

If any file exceeds 200 MB, mine will abort with a log entry — check `state/mempalace-mine.log`.

### 3. Consider filing upstream: mine concurrency

`mempalace mine` has no built-in concurrency guard. The lockfile wrappers are stable but the issue should be fixed upstream. Consider opening an issue at the mempalace repo.

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

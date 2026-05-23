# MemPalace HNSW Auto-Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent MemPalace HNSW/SQLite divergence from silently disabling vector search, with automatic nightly repair and interactive fix prompts in healthcheck.

**Architecture:** Three independent changes: (1) pin `chromadb==1.5.8` in pyproject.toml to freeze the embedded Rust HNSW bindings version, (2) extend `check_mempalace()` in healthcheck.sh to detect HNSW/SQLite count divergence and emit a `run:`-prefixed hint that the existing `hint()` function already auto-promotes to an interactive `[y/N]` fix prompt, (3) register a nightly `mempalace repair` cron at 4am (after the 3am mine) via the existing `install_cron` helper.

**Tech Stack:** bash, Python 3, uv/pyproject.toml, crontab, sqlite3, struct (stdlib)

---

## Context

- `hint()` in healthcheck.sh already offers `[y/N]` execution when the hint starts with `run: ` and stderr is a terminal (lines 44–57). No new prompt helper needed.
- `chromadb-hnswlib` does NOT exist in this venv — the venv has `chromadb 1.5.8` with embedded Rust bindings (`chromadb_rust_bindings`).
- Current HNSW state: 1,056 entries in HNSW vs 467,791 in SQLite — 100% of drawers invisible to vector search.
- The existing HNSW check in `check_mempalace()` only catches link_lists.bin size >200MB. It does not catch SQLite/HNSW count divergence.
- `check_crons()` EXPECTED array does not include `uncle-j-mempalace-mine` or `uncle-j-mempalace-repair`. We add the latter.

---

## Files Modified

| File | Change |
|------|--------|
| `pyproject.toml` | Add `override-dependencies = ["chromadb==1.5.8"]` under `[tool.uv]` |
| `healthcheck.sh` | Fix SQLite hint prefix; add HNSW/SQLite drift sub-step; add `uncle-j-mempalace-repair` to `check_crons` EXPECTED |
| `features/mempalace/install.sh` | Add `MARKER_CRON_REPAIR` constant + repair cron install/uninstall |

---

## Task 1: Pin chromadb version in pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add override-dependencies block**

Open `pyproject.toml`. The `[tool.uv]` section currently ends at:
```toml
[tool.uv]
# Keep the lockfile deterministic.
managed = true
```

Change it to:
```toml
[tool.uv]
# Keep the lockfile deterministic.
managed = true
# Pin chromadb to the version whose embedded Rust HNSW bindings are known-good.
# The chromadb-hnswlib 1.5.x type-confusion bug can corrupt HNSW indexes on upsert.
# Bump this intentionally after verifying repair runs clean on the new version.
override-dependencies = ["chromadb==1.5.8"]
```

- [ ] **Step 2: Apply the lock**

```bash
cd /opt/proj/Uncle-J-s-Refinery
.venv/bin/uv sync --inexact 2>&1 | tail -5
```

Expected: no errors; chromadb stays at 1.5.8.

- [ ] **Step 3: Verify pin took effect**

```bash
.venv/bin/python -c "import importlib.metadata; print(importlib.metadata.version('chromadb'))"
```

Expected output: `1.5.8`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: pin chromadb==1.5.8 to freeze HNSW Rust bindings version"
```

---

## Task 2: Extend healthcheck.sh

**Files:**
- Modify: `healthcheck.sh` — `check_mempalace()` at line 306, `check_crons()` at line 358

### 2a — Fix SQLite FTS5 hint so Y/n fires

The current SQLite FTS5 failure hint uses `repair:` prefix, which the `hint()` function does **not** intercept for Y/n (it only intercepts `run: `).

- [ ] **Step 1: Fix the hint prefix**

Find this block inside `check_mempalace()` (around line 320):
```bash
        bad "SQLite integrity failure: $result"
        hint "repair: sqlite3 $db \"INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('rebuild');\""
        record_fail "mempalace-sqlite"
```

Replace with:
```bash
        bad "SQLite integrity failure: $result"
        hint "run: sqlite3 $db \"INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('rebuild');\""
        record_fail "mempalace-sqlite"
```

- [ ] **Step 2: Verify the change looks correct**

```bash
grep -n "embedding_fulltext_search" healthcheck.sh
```

Expected: line shows `hint "run: sqlite3 ..."`

### 2b — Add HNSW/SQLite drift detection sub-step

Add this new sub-step at the **end** of `check_mempalace()`, immediately before the closing `}` (currently at line 355):

- [ ] **Step 3: Add the drift check**

Find the end of `check_mempalace()`. The last lines currently read:
```bash
    [ "$corrupted" -eq 0 ] && ok "HNSW link_lists.bin sizes normal"
}
```

Replace with:
```bash
    [ "$corrupted" -eq 0 ] && ok "HNSW link_lists.bin sizes normal"

    step "MemPalace — HNSW/SQLite drawer count sync"
    local drift_result
    drift_result=$( "$REPO_ROOT/.venv/bin/python3" - "$HOME/.mempalace/palace" <<'PYEOF'
import sys, sqlite3, struct, pathlib

palace = pathlib.Path(sys.argv[1])
db = palace / "chroma.sqlite3"
if not db.exists():
    print("SKIP")
    sys.exit(0)

try:
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        sqlite_count = conn.execute(
            "SELECT COUNT(*) FROM embedding_fulltext_search_content"
        ).fetchone()[0]
except Exception as e:
    print(f"ERR:{e}")
    sys.exit(0)

hnsw_count = 0
for hdr_path in palace.glob("*/header.bin"):
    try:
        data = hdr_path.read_bytes()
        if len(data) >= 24:
            cur = struct.unpack_from("<I", data, 20)[0]
            hnsw_count = max(hnsw_count, cur)
    except Exception:
        pass

print(f"{sqlite_count}:{hnsw_count}")
PYEOF
    )

    case "$drift_result" in
        SKIP)
            ok "HNSW drift check skipped (no palace db yet)" ;;
        ERR:*)
            warn "HNSW drift check error: ${drift_result#ERR:}" ;;
        *:*)
            local sqlite_n hnsw_n
            sqlite_n="${drift_result%%:*}"
            hnsw_n="${drift_result##*:}"
            if [ "$sqlite_n" -gt 0 ] && [ "$hnsw_n" -lt "$((sqlite_n / 2))" ]; then
                bad "HNSW/SQLite drift: HNSW has ${hnsw_n} elements, SQLite has ${sqlite_n} drawers"
                hint "run: $REPO_ROOT/.venv/bin/mempalace repair"
                record_fail "mempalace-hnsw-drift"
            else
                ok "HNSW/SQLite in sync (HNSW=${hnsw_n}, SQLite=${sqlite_n})"
            fi ;;
    esac
}
```

- [ ] **Step 4: Syntax-check the file**

```bash
bash -n healthcheck.sh && echo "syntax OK"
```

Expected: `syntax OK`

- [ ] **Step 5: Smoke-test the new check**

```bash
./healthcheck.sh --quick 2>&1 | grep -A3 "HNSW/SQLite"
```

Expected: either `X   HNSW/SQLite drift: ...` with fix prompt (if drift present) or `OK  HNSW/SQLite in sync`.

### 2c — Add uncle-j-mempalace-repair to check_crons EXPECTED

- [ ] **Step 6: Add the repair cron to the expected set**

In `check_crons()`, find the `declare -A EXPECTED` block and add one entry:

Find:
```bash
        [uncle-j-jcodemunch-reindex]="bash $REPO_ROOT/scripts/jcodemunch-reindex.sh"
    )
```

Replace with:
```bash
        [uncle-j-jcodemunch-reindex]="bash $REPO_ROOT/scripts/jcodemunch-reindex.sh"
        [uncle-j-mempalace-repair]="mempalace repair"
    )
```

- [ ] **Step 7: Syntax-check again**

```bash
bash -n healthcheck.sh && echo "syntax OK"
```

- [ ] **Step 8: Commit**

```bash
git add healthcheck.sh
git commit -m "feat: healthcheck — HNSW/SQLite drift detection + interactive repair prompt"
```

---

## Task 3: Add nightly repair cron in features/mempalace/install.sh

**Files:**
- Modify: `features/mempalace/install.sh`

- [ ] **Step 1: Add MARKER_CRON_REPAIR constant**

Find the constants block near the top (around line 20):
```bash
MARKER_STOP="uncle-j-mempalace-convos"
MARKER_CRON="uncle-j-mempalace-mine"
```

Replace with:
```bash
MARKER_STOP="uncle-j-mempalace-convos"
MARKER_CRON="uncle-j-mempalace-mine"
MARKER_CRON_REPAIR="uncle-j-mempalace-repair"
```

- [ ] **Step 2: Add uninstall path for repair cron**

Find the `--uninstall` block:
```bash
  step "Removing cron job ($MARKER_CRON)"
  remove_cron "$MARKER_CRON"
  ok "Cron removed"
  step "Done"
  exit 0
```

Replace with:
```bash
  step "Removing cron job ($MARKER_CRON)"
  remove_cron "$MARKER_CRON"
  ok "Cron removed"
  step "Removing repair cron job ($MARKER_CRON_REPAIR)"
  remove_cron "$MARKER_CRON_REPAIR"
  ok "Repair cron removed"
  step "Done"
  exit 0
```

- [ ] **Step 3: Add repair cron install after the existing mine cron**

Find the existing cron install block near the end of the install path:
```bash
step "Registering daily cron (3am)"
CRON_ENTRY="0 3 * * * ${MEMPALACE_BIN} mine ${PROJ_ROOT} >> ${PROJ_ROOT}/state/mempalace-mine.log 2>&1"
install_cron "$MARKER_CRON" "$CRON_ENTRY"
ok "Cron installed: 0 3 * * *"
```

Replace with:
```bash
step "Registering daily cron (3am — mine)"
CRON_ENTRY="0 3 * * * ${MEMPALACE_BIN} mine ${PROJ_ROOT} >> ${PROJ_ROOT}/state/mempalace-mine.log 2>&1"
install_cron "$MARKER_CRON" "$CRON_ENTRY"
ok "Cron installed: 0 3 * * *"

step "Registering nightly repair cron (4am — HNSW rebuild)"
CRON_REPAIR="0 4 * * * ${MEMPALACE_BIN} repair >> ${PROJ_ROOT}/state/mempalace-repair.log 2>&1"
install_cron "$MARKER_CRON_REPAIR" "$CRON_REPAIR"
ok "Cron installed: 0 4 * * *"
```

- [ ] **Step 4: Update the summary block**

Find the summary printf lines at the bottom:
```bash
  printf '  Daily cron:       3am — re-mines project code\n'
```

Replace with:
```bash
  printf '  Daily cron (mine):   3am — re-mines project code\n'
  printf '  Nightly cron (repair): 4am — rebuilds HNSW index from SQLite\n'
```

- [ ] **Step 5: Run the install script to register the new cron**

```bash
bash /opt/proj/Uncle-J-s-Refinery/features/mempalace/install.sh 2>&1 | tail -15
```

Expected: lines showing both crons installed.

- [ ] **Step 6: Verify cron is registered**

```bash
crontab -l | grep mempalace
```

Expected: two lines — one for `uncle-j-mempalace-mine` (3am) and one for `uncle-j-mempalace-repair` (4am).

- [ ] **Step 7: Verify healthcheck now passes the cron check**

```bash
./healthcheck.sh --quick 2>&1 | grep -E "mempalace-(mine|repair)|HNSW|cron"
```

Expected: `OK  cron: uncle-j-mempalace-repair` visible (after cron check section).

- [ ] **Step 8: Commit**

```bash
git add features/mempalace/install.sh
git commit -m "feat: add nightly mempalace repair cron (4am) to prevent HNSW drift"
```

---

## Self-Review

**Spec coverage:**
- Pin chromadb version → Task 1 ✓
- HNSW/SQLite drift detection → Task 2b ✓
- `[Y/n]` fix prompt when fixable → Task 2a (fixes SQLite FTS5 hint) + Task 2b (uses `run:` prefix, Y/n auto-fires via existing `hint()`) ✓
- Nightly repair cron → Task 3 ✓
- Cron registered in healthcheck EXPECTED → Task 2c ✓
- Uninstall path updated → Task 3 Step 2 ✓

**Placeholder scan:** None — all steps have exact file paths, line references, and complete code blocks.

**Type consistency:** Only bash and Python snippets — no type signatures to drift.

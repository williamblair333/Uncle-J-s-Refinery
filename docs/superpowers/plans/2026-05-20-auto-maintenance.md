# Auto-Maintenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the four recurring maintenance gaps (stale jcodemunch index, packages behind HEAD, CLAUDE.md routing drift, untracked skill files) by wiring three new scripts and two new crons that run without human intervention.

**Architecture:** `scripts/jcodemunch-reindex.sh` handles incremental reindexing (called by cron + post-merge hook). `scripts/auto-maintain.sh` handles threshold-based package upgrades, post-upgrade CLAUDE.md sync via `jcodemunch-mcp claude-md --format append`, and auto-commit of untracked global-skills files. Three new healthcheck functions guard against regression.

**Tech Stack:** bash, `jcodemunch-mcp index` CLI, `jcodemunch-mcp claude-md --format append` CLI, `uv lock --upgrade-package`, `claude -p` (headless skill invocation), crontab

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `scripts/jcodemunch-reindex.sh` | Incremental reindex + SHA stamp |
| Create | `scripts/auto-maintain.sh` | Threshold upgrade + CLAUDE.md sync + skills autocommit |
| Modify | `scripts/post-merge-hook.sh` | Add jcodemunch reindex when code files change |
| Modify | `healthcheck.sh` | Add 3 new checks; expand check_crons |
| Modify | `install.sh` | Register 2 new crons |

---

## Task 1: `scripts/jcodemunch-reindex.sh`

**Files:**
- Create: `scripts/jcodemunch-reindex.sh`

- [ ] **Step 1: Create the reindex script**

```bash
cat > /opt/proj/Uncle-J-s-Refinery/scripts/jcodemunch-reindex.sh << 'SCRIPT'
#!/usr/bin/env bash
# Incremental jcodemunch index refresh. Safe to run on cron or from post-merge hook.
# Stamps the indexed git HEAD to state/jcodemunch-last-indexed.sha on success.
# Exits 0 on success, 1 on failure.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
JCODEMUNCH="$PROJ_ROOT/.venv/bin/jcodemunch-mcp"
STAMP="$PROJ_ROOT/state/jcodemunch-last-indexed.sha"
LOG="$PROJ_ROOT/state/jcodemunch-reindex.log"

mkdir -p "$PROJ_ROOT/state"
log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

if [[ ! -x "$JCODEMUNCH" ]]; then
    log "ERROR: jcodemunch-mcp not found at $JCODEMUNCH"
    exit 1
fi

log "Starting incremental reindex of $PROJ_ROOT ..."
if "$JCODEMUNCH" index "$PROJ_ROOT" --no-ai-summaries >> "$LOG" 2>&1; then
    SHA=$(git -C "$PROJ_ROOT" rev-parse HEAD 2>/dev/null || echo "unknown")
    echo "$SHA" > "$STAMP"
    log "Reindex complete. Indexed SHA: $SHA"
    exit 0
else
    log "ERROR: jcodemunch-mcp index failed (see above)"
    exit 1
fi
SCRIPT
chmod +x /opt/proj/Uncle-J-s-Refinery/scripts/jcodemunch-reindex.sh
```

- [ ] **Step 2: Verify the script runs without error**

```bash
bash /opt/proj/Uncle-J-s-Refinery/scripts/jcodemunch-reindex.sh
# Expected: exit 0, state/jcodemunch-last-indexed.sha written with current HEAD SHA
cat /opt/proj/Uncle-J-s-Refinery/state/jcodemunch-last-indexed.sha
```

Expected output: a 40-char git SHA.

- [ ] **Step 3: Commit**

```bash
git -C /opt/proj/Uncle-J-s-Refinery add scripts/jcodemunch-reindex.sh state/jcodemunch-last-indexed.sha
git -C /opt/proj/Uncle-J-s-Refinery commit -m "feat: add jcodemunch-reindex.sh — incremental index + SHA stamp"
```

---

## Task 2: Post-merge hook — add jcodemunch reindex

**Files:**
- Modify: `scripts/post-merge-hook.sh` — after the existing jdocmunch reindex block

The existing block at line ~113 reindexes jdocmunch when `.md` files change. Add a parallel block that reindexes jcodemunch when code files change.

- [ ] **Step 1: Add jcodemunch reindex block to post-merge-hook.sh**

Find the existing jdocmunch block (it starts with `if echo "$CHANGED" | grep -qE '\.md$'`).
Insert the following block immediately after the closing `fi` of that block (before the `# Deliver:` comment):

```bash
# Auto re-index jcodemunch when source files changed
# (silent — no user action needed; logged to post-merge.log)
if echo "$CHANGED" | grep -qE '\.(py|sh|ts|tsx|js|json|toml)$'; then
    REINDEX="$PROJ_ROOT/scripts/jcodemunch-reindex.sh"
    if [[ -x "$REINDEX" ]]; then
        log "post-merge: code files changed — re-indexing jcodemunch..."
        bash "$REINDEX" && \
            log "post-merge: jcodemunch re-index complete" || \
            log "post-merge: jcodemunch re-index failed (non-fatal)"
    fi
fi
```

- [ ] **Step 2: Verify the block is syntactically valid**

```bash
bash -n /opt/proj/Uncle-J-s-Refinery/scripts/post-merge-hook.sh
# Expected: no output (syntax OK)
```

- [ ] **Step 3: Commit**

```bash
git -C /opt/proj/Uncle-J-s-Refinery add scripts/post-merge-hook.sh
git -C /opt/proj/Uncle-J-s-Refinery commit -m "feat: post-merge hook reindexes jcodemunch on code file changes"
```

---

## Task 3: `scripts/auto-maintain.sh`

This is the core orchestrator. It runs nightly and handles three things:
1. Threshold-based package upgrade
2. CLAUDE.md sync after any upgrade (via `jcodemunch-mcp claude-md --format append`)
3. Auto-commit of untracked `global-skills/*/SKILL.md` files

Thresholds: jcodemunch/jdatamunch/jdocmunch = 20 commits behind, mempalace = 5 commits behind.

**Files:**
- Create: `scripts/auto-maintain.sh`

- [ ] **Step 1: Create auto-maintain.sh**

```bash
cat > /opt/proj/Uncle-J-s-Refinery/scripts/auto-maintain.sh << 'SCRIPT'
#!/usr/bin/env bash
# Nightly maintenance: threshold-based package upgrades, CLAUDE.md sync,
# and auto-commit of untracked global-skills files.
#
# Usage:
#   bash scripts/auto-maintain.sh            # full run
#   bash scripts/auto-maintain.sh --dry-run  # print what would change, no writes
#
# Exits 0 always (cron must not fail loudly on transient GitHub API issues).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCKFILE="$PROJ_ROOT/uv.lock"
ENV_FILE="$PROJ_ROOT/.env"
LOG="$PROJ_ROOT/state/auto-maintain.log"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo 'claude')}"
DRY_RUN=0

mkdir -p "$PROJ_ROOT/state"
log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }
info() { log "INFO  $*"; }
warn() { log "WARN  $*"; }

for arg in "$@"; do
    [[ "$arg" == "--dry-run" ]] && DRY_RUN=1
done
[[ "$DRY_RUN" -eq 1 ]] && info "DRY RUN — no changes will be made"

[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

# ── Thresholds ────────────────────────────────────────────────────────────────
declare -A THRESHOLDS=(
    [jcodemunch-mcp]=20
    [jdatamunch-mcp]=20
    [jdocmunch-mcp]=20
    [mempalace]=5
)
declare -A GITHUB=(
    [jcodemunch-mcp]="jgravelle/jcodemunch-mcp"
    [jdatamunch-mcp]="jgravelle/jdatamunch-mcp"
    [jdocmunch-mcp]="jgravelle/jdocmunch-mcp"
    [mempalace]="MemPalace/mempalace"
)

# ── GitHub helpers (duplicated from check-stack-freshness.sh to avoid sourcing
#    a script with side effects) ───────────────────────────────────────────────
_gh_curl() {
    local auth_args=()
    [[ -n "${GITHUB_TOKEN:-}" ]] && auth_args=(-H "Authorization: Bearer $GITHUB_TOKEN")
    curl -sf "${auth_args[@]}" -H "Accept: application/vnd.github.v3+json" "$@"
}

parse_lock_sha() {
    local pkg=$1
    python3 - "$pkg" "$LOCKFILE" << 'PYEOF' 2>/dev/null || echo "?"
import sys, re
pkg, lockfile = sys.argv[1], sys.argv[2]
try:
    content = open(lockfile).read()
    pattern = (r'\[\[package\]\]\s+name\s*=\s*"' + re.escape(pkg) +
               r'".*?source\s*=\s*\{\s*git\s*=\s*"[^"]+#([a-f0-9]{40})"')
    m = re.search(pattern, content, re.DOTALL)
    print(m.group(1)[:7] if m else "?")
except Exception:
    print("?")
PYEOF
}

commits_behind() {
    local pkg=$1 github=$2
    local installed_sha
    installed_sha=$(parse_lock_sha "$pkg")
    [[ "$installed_sha" == "?" ]] && echo 0 && return
    _gh_curl "https://api.github.com/repos/$github/compare/${installed_sha}...HEAD" \
        | python3 -c "import sys,json
try:
    d=json.load(sys.stdin); print(d.get('ahead_by',0))
except Exception:
    print(0)" 2>/dev/null || echo 0
}

# ── Part A: threshold-based upgrade ──────────────────────────────────────────
info "=== Part A: Package freshness check ==="
PACKAGES_TO_UPGRADE=()

for pkg in jcodemunch-mcp jdatamunch-mcp jdocmunch-mcp mempalace; do
    threshold="${THRESHOLDS[$pkg]}"
    github="${GITHUB[$pkg]}"
    behind=$(commits_behind "$pkg" "$github")
    info "$pkg: ${behind} commits behind HEAD (threshold: ${threshold})"
    if [[ "$behind" -gt "$threshold" ]]; then
        info "$pkg EXCEEDS threshold — queued for upgrade"
        PACKAGES_TO_UPGRADE+=("$pkg")
    fi
done

UPGRADED=0
if [[ "${#PACKAGES_TO_UPGRADE[@]}" -gt 0 ]]; then
    UPGRADE_FLAGS=""
    for pkg in "${PACKAGES_TO_UPGRADE[@]}"; do
        UPGRADE_FLAGS="$UPGRADE_FLAGS --upgrade-package $pkg"
    done

    info "Upgrading: ${PACKAGES_TO_UPGRADE[*]}"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        info "DRY RUN: would run: cd $PROJ_ROOT && uv lock $UPGRADE_FLAGS && uv sync --inexact"
    else
        if (cd "$PROJ_ROOT" && uv lock $UPGRADE_FLAGS && uv sync --inexact) >> "$LOG" 2>&1; then
            info "Upgrade succeeded."
            UPGRADED=1
        else
            warn "Upgrade FAILED — see $LOG for details"
        fi
    fi
else
    info "All packages within threshold. No upgrade needed."
fi

# ── Part B: CLAUDE.md sync after upgrade ─────────────────────────────────────
info "=== Part B: CLAUDE.md sync ==="
JCODEMUNCH="$PROJ_ROOT/.venv/bin/jcodemunch-mcp"

if [[ "$UPGRADED" -eq 1 && -x "$JCODEMUNCH" ]]; then
    # Get tools not yet in our CLAUDE.md
    NEW_TOOLS=$("$JCODEMUNCH" claude-md --format append 2>/dev/null || true)
    if [[ -n "$NEW_TOOLS" && "$NEW_TOOLS" != *"No new tools"* ]]; then
        info "New tools detected in jcodemunch. Triggering post-upgrade-mcp-integration..."
        if [[ "$DRY_RUN" -eq 1 ]]; then
            info "DRY RUN: would run claude -p to sync CLAUDE.md routing"
        else
            SYNC_PROMPT="The jcodemunch-mcp package was just upgraded in $PROJ_ROOT. \
Run the post-upgrade-mcp-integration skill to check for new tools and update \
both the project CLAUDE.md and ~/.claude/CLAUDE.md routing policy, then commit. \
The new tools not yet in CLAUDE.md are:\n$NEW_TOOLS"
            if "$CLAUDE_BIN" -p "$SYNC_PROMPT" >> "$LOG" 2>&1; then
                info "CLAUDE.md sync complete."
            else
                warn "CLAUDE.md sync claude -p invocation failed (non-fatal)"
            fi
        fi
    else
        info "No new tools to add to CLAUDE.md."
    fi
elif [[ "$UPGRADED" -eq 0 ]]; then
    info "No upgrade performed — CLAUDE.md sync skipped."
fi

# ── Part C: auto-commit untracked global-skills files ────────────────────────
info "=== Part C: Untracked global-skills check ==="

UNTRACKED=$(git -C "$PROJ_ROOT" status --porcelain 2>/dev/null \
    | grep "^?? global-skills/" | sed 's/^?? //' | sed 's|/$||' || true)

if [[ -z "$UNTRACKED" ]]; then
    info "No untracked global-skills files."
else
    SKILL_NAMES=()
    SKILL_DESCRIPTIONS=()

    while IFS= read -r skill_dir; do
        skill_name=$(basename "$skill_dir")
        skill_md="$PROJ_ROOT/$skill_dir/SKILL.md"
        if [[ ! -f "$skill_md" ]]; then
            continue
        fi
        desc=$(python3 -c "
import sys, re
content = open('$skill_md').read()
m = re.search(r'^description:\s*(.+)$', content, re.MULTILINE)
print(m.group(1).strip() if m else 'no description')
" 2>/dev/null || echo "no description")
        SKILL_NAMES+=("$skill_name")
        SKILL_DESCRIPTIONS+=("$desc")
    done <<< "$UNTRACKED"

    if [[ "${#SKILL_NAMES[@]}" -eq 0 ]]; then
        info "No SKILL.md files found in untracked directories."
    else
        info "Found ${#SKILL_NAMES[@]} untracked skill(s): ${SKILL_NAMES[*]}"

        if [[ "$DRY_RUN" -eq 1 ]]; then
            info "DRY RUN: would auto-commit skills: ${SKILL_NAMES[*]}"
        else
            TODAY=$(date '+%Y-%m-%d')
            # Build CHANGELOG entry
            SKILL_LIST=""
            for i in "${!SKILL_NAMES[@]}"; do
                SKILL_LIST="${SKILL_LIST}"$'\n'"- \`${SKILL_NAMES[$i]}\` — ${SKILL_DESCRIPTIONS[$i]}"
            done

            # Prepend CHANGELOG entry after the header line
            python3 - "$PROJ_ROOT/CHANGELOG.md" "$TODAY" "$SKILL_LIST" << 'PYEOF'
import sys, pathlib, datetime
changelog, today, skill_list = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(changelog)
content = p.read_text()
# Insert after the first '---' separator
insert_after = content.find('\n---\n')
if insert_after == -1:
    insert_after = content.find('\n\n')
entry = f"\n## {today} — auto-maintained: new skills committed\n\n### New skills\n{skill_list}\n\n---\n"
new_content = content[:insert_after+5] + entry + content[insert_after+5:]
p.write_text(new_content)
PYEOF

            # Update HANDOFF last-updated date
            sed -i "s/^\*Last updated: .*\*/*Last updated: $TODAY*/" "$PROJ_ROOT/HANDOFF.md"

            # Stage and commit
            git -C "$PROJ_ROOT" add global-skills/ CHANGELOG.md HANDOFF.md
            COUNT="${#SKILL_NAMES[@]}"
            git -C "$PROJ_ROOT" commit -m "feat: auto-commit ${COUNT} new global skill(s): ${SKILL_NAMES[*]}" \
                --author="Uncle J Auto-Maintain <auto@uncle-j.local>" || \
                info "git commit failed or nothing to commit"
            info "Skills committed."
        fi
    fi
fi

# ── Telegram notification ─────────────────────────────────────────────────────
if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" && "$DRY_RUN" -eq 0 ]]; then
    SUMMARY="🔧 auto-maintain: "
    [[ "$UPGRADED" -eq 1 ]] && SUMMARY+="upgraded ${PACKAGES_TO_UPGRADE[*]}. "
    [[ "${#SKILL_NAMES[@]:-0}" -gt 0 ]] && SUMMARY+="committed ${#SKILL_NAMES[@]} skill(s). "
    [[ "$UPGRADED" -eq 0 && "${#SKILL_NAMES[@]:-0}" -eq 0 ]] && SUMMARY+="nothing to do."
    source "$PROJ_ROOT/lib/notify.sh" 2>/dev/null && notify_send_text "$SUMMARY" || true
fi

info "=== auto-maintain complete ==="
exit 0
SCRIPT
chmod +x /opt/proj/Uncle-J-s-Refinery/scripts/auto-maintain.sh
```

- [ ] **Step 2: Run dry-run and verify output**

```bash
bash /opt/proj/Uncle-J-s-Refinery/scripts/auto-maintain.sh --dry-run 2>&1
```

Expected: log lines for Part A (commits behind each package), Part B (CLAUDE.md sync dry-run), Part C (untracked skills dry-run). No git commits, no package changes.

- [ ] **Step 3: Verify bash syntax**

```bash
bash -n /opt/proj/Uncle-J-s-Refinery/scripts/auto-maintain.sh
# Expected: no output
```

- [ ] **Step 4: Commit**

```bash
git -C /opt/proj/Uncle-J-s-Refinery add scripts/auto-maintain.sh
git -C /opt/proj/Uncle-J-s-Refinery commit -m "feat: add auto-maintain.sh — threshold upgrade, CLAUDE.md sync, skills autocommit"
```

---

## Task 4: Healthcheck — 3 new checks

**Files:**
- Modify: `healthcheck.sh` — add 3 functions, call them in main, expand `check_crons`

- [ ] **Step 1: Add `check_jcodemunch_index_fresh` function**

Insert the following function before the `# ===== full-mode extras` line in `healthcheck.sh`:

```bash
# ----- 9i. jcodemunch index not stale --------------------------------------
check_jcodemunch_index_fresh() {
    step "jcodemunch — index up to date with git HEAD"
    local stamp="$REPO_ROOT/state/jcodemunch-last-indexed.sha"
    local current_head
    current_head=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo "unknown")
    if [[ ! -f "$stamp" ]]; then
        bad "jcodemunch index has never been stamped — run: bash $REPO_ROOT/scripts/jcodemunch-reindex.sh"
        hint "run: bash $REPO_ROOT/scripts/jcodemunch-reindex.sh"
        record_fail "jcodemunch-not-indexed"
        return
    fi
    local indexed_head
    indexed_head=$(cat "$stamp" 2>/dev/null | tr -d '[:space:]')
    if [[ "$indexed_head" == "$current_head" ]]; then
        ok "jcodemunch index at HEAD ($current_head)"
    else
        # Count commits between indexed and current
        local behind
        behind=$(git -C "$REPO_ROOT" rev-list --count "${indexed_head}..${current_head}" 2>/dev/null || echo "?")
        bad "jcodemunch index is ${behind} commit(s) stale (indexed=$indexed_head current=$current_head)"
        hint "run: bash $REPO_ROOT/scripts/jcodemunch-reindex.sh"
        record_fail "jcodemunch-index-stale"
    fi
}

# ----- 9j. no untracked global-skills files --------------------------------
check_untracked_skills() {
    step "global-skills — no untracked SKILL.md files"
    local untracked
    untracked=$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null \
        | grep "^?? global-skills/" || true)
    if [[ -z "$untracked" ]]; then
        ok "no untracked global-skills files"
    else
        local count
        count=$(printf '%s\n' "$untracked" | wc -l)
        bad "${count} untracked global-skills entry(ies) not yet committed"
        printf '%s\n' "$untracked" | while IFS= read -r line; do
            printf '        %s\n' "$line"
        done >&2
        hint "auto-maintain.sh will commit these tonight, or run it now: bash $REPO_ROOT/scripts/auto-maintain.sh"
        record_fail "untracked-skills"
    fi
}

# ----- 9k. auto-maintain cron registered -----------------------------------
check_auto_maintain_cron() {
    step "crontab — auto-maintain crons registered"
    local tab
    tab="$(crontab -l 2>/dev/null || true)"
    local missing=()
    for label in uncle-j-auto-maintain uncle-j-jcodemunch-reindex; do
        if printf '%s\n' "$tab" | grep -q "$label"; then
            ok "cron: $label"
        else
            missing+=("$label")
        fi
    done
    if [[ "${#missing[@]}" -gt 0 ]]; then
        for m in "${missing[@]}"; do
            bad "cron missing: $m"
        done
        hint "run: bash $REPO_ROOT/install.sh   (re-registers crons)"
        record_fail "cron-missing(${missing[0]})"
    fi
}
```

- [ ] **Step 2: Call the three new functions in main**

Find the line `check_secrets` near the end of the main execution block and add the three new calls after it:

```bash
check_secrets
check_jcodemunch_index_fresh
check_untracked_skills
check_auto_maintain_cron
```

- [ ] **Step 3: Expand `check_crons` to include the two new crons**

In `healthcheck.sh`, inside the `check_crons()` function (starts ~line 283), find the `declare -A EXPECTED=(` block (the one listing `uncle-j-stack-alerts-send`, `uncle-j-dreaming`, etc.) and add two new entries before the closing `)`:

```bash
[uncle-j-auto-maintain]="bash $REPO_ROOT/scripts/auto-maintain.sh"
[uncle-j-jcodemunch-reindex]="bash $REPO_ROOT/scripts/jcodemunch-reindex.sh"
```

- [ ] **Step 4: Verify healthcheck syntax**

```bash
bash -n /opt/proj/Uncle-J-s-Refinery/healthcheck.sh
# Expected: no output
```

- [ ] **Step 5: Run healthcheck and confirm the 3 new checks appear**

```bash
bash /opt/proj/Uncle-J-s-Refinery/healthcheck.sh 2>&1 | grep -E "(jcodemunch — index|global-skills|auto-maintain cron)"
```

Expected: 3 lines printed (the new checks running). The first two will likely fail until the crons are registered in Task 5.

- [ ] **Step 6: Commit**

```bash
git -C /opt/proj/Uncle-J-s-Refinery add healthcheck.sh
git -C /opt/proj/Uncle-J-s-Refinery commit -m "feat: healthcheck — index freshness, untracked skills, auto-maintain cron checks"
```

---

## Task 5: Cron wiring in install.sh

**Files:**
- Modify: `install.sh` — add two new crons to the cron registration block

The existing cron block is around line 250 (`step "Setting up MemPalace backup + health-check cron jobs"`). Add the two new crons to the same loop.

- [ ] **Step 1: Add two cron entries to the cron loop in install.sh**

Find the `for entry in \` loop that registers `uncle-j-mempalace-backup` and `uncle-j-mempalace-health`. Add two new entries to it:

```bash
    "uncle-j-jcodemunch-reindex|0 1 * * * PATH=/home/bill/.local/bin:/usr/local/bin:/usr/bin:/bin bash $STACK_ROOT/scripts/jcodemunch-reindex.sh >> $STACK_ROOT/state/jcodemunch-reindex.log 2>&1" \
    "uncle-j-auto-maintain|0 3 * * * PATH=/home/bill/.local/bin:/usr/local/bin:/usr/bin:/bin CLAUDE_BIN=/home/bill/.local/bin/claude bash $STACK_ROOT/scripts/auto-maintain.sh >> $STACK_ROOT/state/auto-maintain.log 2>&1" \
```

Schedule rationale:
- `0 1 * * *` (1am) — reindex runs before dreaming (2am) so the dream synthesizer uses a fresh index
- `0 3 * * *` (3am) — auto-maintain runs after dreaming; upgrades land while the user sleeps

- [ ] **Step 2: Register the crons now without re-running full install.sh**

```bash
PROJ_ROOT=/opt/proj/Uncle-J-s-Refinery
for entry in \
    "uncle-j-jcodemunch-reindex|0 1 * * * PATH=/home/bill/.local/bin:/usr/local/bin:/usr/bin:/bin bash $PROJ_ROOT/scripts/jcodemunch-reindex.sh >> $PROJ_ROOT/state/jcodemunch-reindex.log 2>&1" \
    "uncle-j-auto-maintain|0 3 * * * PATH=/home/bill/.local/bin:/usr/local/bin:/usr/bin:/bin CLAUDE_BIN=/home/bill/.local/bin/claude bash $PROJ_ROOT/scripts/auto-maintain.sh >> $PROJ_ROOT/state/auto-maintain.log 2>&1"
do
    tag="${entry%%|*}"
    line="${entry#*|}"
    if crontab -l 2>/dev/null | grep -q "$tag"; then
        echo "cron already registered: $tag"
    else
        ( crontab -l 2>/dev/null; printf '# %s\n%s\n' "$tag" "$line" ) | crontab -
        echo "cron registered: $tag"
    fi
done
```

- [ ] **Step 3: Verify both crons are in crontab**

```bash
crontab -l | grep -E "uncle-j-(jcodemunch-reindex|auto-maintain)"
# Expected: 2 lines
```

- [ ] **Step 4: Verify healthcheck now passes the cron checks**

```bash
bash /opt/proj/Uncle-J-s-Refinery/healthcheck.sh 2>&1 | grep -E "(auto-maintain cron|cron: uncle-j-auto|cron: uncle-j-jcodemunch)"
# Expected: OK lines for both new crons
```

- [ ] **Step 5: Commit**

```bash
git -C /opt/proj/Uncle-J-s-Refinery add install.sh
git -C /opt/proj/Uncle-J-s-Refinery commit -m "feat: register auto-maintain and jcodemunch-reindex crons in install.sh"
```

---

## Task 6: Run full healthcheck + update docs

- [ ] **Step 1: Run full healthcheck**

```bash
bash /opt/proj/Uncle-J-s-Refinery/healthcheck.sh --full 2>&1
```

Expected: `HEALTHCHECK: ok` — all checks including the 3 new ones should pass now that crons are registered and the index stamp exists.

- [ ] **Step 2: Update CHANGELOG.md**

Add the following entry at the top of CHANGELOG.md (after the `---` separator):

```markdown
## 2026-05-20 — auto-maintenance scripts and healthcheck guards

### New scripts
- `scripts/jcodemunch-reindex.sh` — incremental reindex, stamps `state/jcodemunch-last-indexed.sha`
- `scripts/auto-maintain.sh` — nightly: threshold-based upgrades (jcodemunch/jdatamunch/jdocmunch ≥20 commits, mempalace ≥5), post-upgrade CLAUDE.md sync via `jcodemunch-mcp claude-md --format append`, auto-commit untracked global-skills

### Healthcheck additions
- `check_jcodemunch_index_fresh` — compares stamped SHA to current HEAD
- `check_untracked_skills` — fails when global-skills/ has uncommitted SKILL.md files
- `check_auto_maintain_cron` — verifies both new crons are registered

### Crons added
- `uncle-j-jcodemunch-reindex` — 1am daily
- `uncle-j-auto-maintain` — 3am daily

### Post-merge hook
- Now reindexes jcodemunch when `.py/.sh/.ts/.json/.toml` files change
```

- [ ] **Step 3: Update HANDOFF.md**

Update the `*Last updated:*` line to `2026-05-20` and add a `### 2026-05-20 (session 2)` entry in the "What happened" section:

```markdown
### 2026-05-20 (session 2)
- **Auto-maintenance**: `scripts/auto-maintain.sh` + `scripts/jcodemunch-reindex.sh` created; 2 new crons (1am reindex, 3am auto-maintain); post-merge hook reindexes jcodemunch on code changes; 3 new healthcheck guards
```

- [ ] **Step 4: Final commit**

```bash
git -C /opt/proj/Uncle-J-s-Refinery add CHANGELOG.md HANDOFF.md
git -C /opt/proj/Uncle-J-s-Refinery commit -m "docs: update CHANGELOG and HANDOFF for auto-maintenance implementation"
```

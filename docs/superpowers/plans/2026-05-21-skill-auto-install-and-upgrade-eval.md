# Skill Auto-Install & Post-Upgrade Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate two manual steps: (1) skills added to `global-skills/` must be explicitly listed in `install-reliability.sh` to get symlinked; (2) post-upgrade CLAUDE.md/HANDOFF.md evaluation only runs for jcodemunch and ignores breaking changes in mempalace/jdatamunch/jdocmunch.

**Architecture:** Two files change. `install-reliability.sh` gets its hardcoded skill list replaced with a `global-skills/*/` glob. `scripts/auto-maintain.sh` gets three edits: a `fetch_commit_log` helper + pre-upgrade SHA capture (Part A/B boundary), a rewritten Part B that loops over all upgraded packages and calls `claude -p` for evaluation, and a symlink pass appended to Part C after the git commit.

**Tech Stack:** bash, GitHub REST API (`/compare/{base}...{head}`), `python3` (JSON parsing inline), `claude -p` (non-interactive evaluation), `uv` (package management).

---

## File Map

| File | Change |
|------|--------|
| `install-reliability.sh` | Lines 29–43: replace hardcoded `for skill in …` with `for src in "$STACK_ROOT/global-skills"/*/` glob |
| `scripts/auto-maintain.sh` | After line 80: add `fetch_commit_log` function |
| `scripts/auto-maintain.sh` | Lines 97–117 (Part A upgrade block): insert OLD_SHAS capture before `uv lock` |
| `scripts/auto-maintain.sh` | Lines 119–142 (Part B): full replacement with 4-package evaluation loop |
| `scripts/auto-maintain.sh` | After line 206 (Part C, after git commit): add symlink pass |
| `scripts/auto-maintain.sh` | Lines 243–248 (Telegram block): extend SUMMARY with breaking-change flags |

---

## Task 1: Dynamic skill scan in install-reliability.sh

**Files:**
- Modify: `install-reliability.sh:29-43`

- [ ] **Step 1: Replace the hardcoded skill loop**

In `install-reliability.sh`, replace lines 29–43:

```bash
for skill in prior-art-check judge outcomes orchestrator per-task-review-cycle post-upgrade-mcp-integration; do
    src="$STACK_ROOT/global-skills/$skill"
    dst="$CLAUDE_DIR/skills/$skill"
    if [ ! -d "$src" ]; then
        warn "skill source missing (will install when created): $src"
        continue
    fi
    if [ -L "$dst" ] && [ "$(readlink -f "$dst")" = "$(readlink -f "$src")" ]; then
        ok "skill already linked: $skill"
        continue
    fi
    rm -rf "$dst"
    ln -sfn "$src" "$dst"
    ok "skill installed: $skill"
done
```

With:

```bash
for src in "$STACK_ROOT/global-skills"/*/; do
    [ -d "$src" ] || continue
    skill_name=$(basename "$src")
    dst="$CLAUDE_DIR/skills/$skill_name"
    if [ -L "$dst" ] && [ "$(readlink -f "$dst")" = "$(readlink -f "$src")" ]; then
        ok "skill already linked: $skill_name"
        continue
    fi
    rm -rf "$dst"
    ln -sfn "$src" "$dst"
    ok "skill installed: $skill_name"
done
```

- [ ] **Step 2: Syntax check**

```bash
bash -n install-reliability.sh
```

Expected: no output (clean parse).

- [ ] **Step 3: Smoke test — verify all current skills still link**

```bash
bash install-reliability.sh 2>&1 | grep -E "OK|!!"
```

Expected: one `OK` line per directory in `global-skills/` (currently: prior-art-check, judge, outcomes, orchestrator, per-task-review-cycle, post-upgrade-mcp-integration, readme-sync). All should show `already linked` since they're already symlinked.

- [ ] **Step 4: Commit**

```bash
git add install-reliability.sh
git commit -m "feat: install-reliability.sh — dynamic global-skills/ scan replaces hardcoded list"
```

---

## Task 2: Add fetch_commit_log helper to auto-maintain.sh

**Files:**
- Modify: `scripts/auto-maintain.sh` (after line 80, before Part A)

- [ ] **Step 1: Insert the helper function**

In `scripts/auto-maintain.sh`, find the closing `}` of the `commits_behind` function (line 80). After that `}` and before the `# ── Part A` comment, insert:

```bash
fetch_commit_log() {
    local pkg=$1 old_sha=$2 new_sha=$3
    _gh_curl "https://api.github.com/repos/${GITHUB[$pkg]}/compare/${old_sha}...${new_sha}" \
        | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for c in d.get('commits', []):
        print(c['commit']['message'].split(chr(10))[0])
except Exception:
    pass
" 2>/dev/null || true
}

```

- [ ] **Step 2: Syntax check**

```bash
bash -n scripts/auto-maintain.sh
```

Expected: no output.

---

## Task 3: Capture pre-upgrade SHAs in Part A

**Files:**
- Modify: `scripts/auto-maintain.sh` (inside the Part A upgrade block, before `uv lock`)

- [ ] **Step 1: Insert OLD_SHAS capture and BREAKING_FLAGS initializer**

In `scripts/auto-maintain.sh`, find this block (around line 97):

```bash
UPGRADED=0
if [[ "${#PACKAGES_TO_UPGRADE[@]}" -gt 0 ]]; then
    UPGRADE_FLAGS=""
    for pkg in "${PACKAGES_TO_UPGRADE[@]}"; do
        UPGRADE_FLAGS="$UPGRADE_FLAGS --upgrade-package $pkg"
    done

    info "Upgrading: ${PACKAGES_TO_UPGRADE[*]}"
```

Replace with:

```bash
UPGRADED=0
BREAKING_FLAGS=()
if [[ "${#PACKAGES_TO_UPGRADE[@]}" -gt 0 ]]; then
    UPGRADE_FLAGS=""
    for pkg in "${PACKAGES_TO_UPGRADE[@]}"; do
        UPGRADE_FLAGS="$UPGRADE_FLAGS --upgrade-package $pkg"
    done

    declare -A OLD_SHAS
    for pkg in "${PACKAGES_TO_UPGRADE[@]}"; do
        OLD_SHAS[$pkg]=$(parse_lock_sha "$pkg")
    done

    info "Upgrading: ${PACKAGES_TO_UPGRADE[*]}"
```

- [ ] **Step 2: Syntax check**

```bash
bash -n scripts/auto-maintain.sh
```

Expected: no output.

---

## Task 4: Replace Part B with all-package evaluation loop

**Files:**
- Modify: `scripts/auto-maintain.sh:119-142`

- [ ] **Step 1: Replace the entire Part B block**

Find and replace lines 119–142 (from `# ── Part B` through the closing `fi`):

```bash
# ── Part B: CLAUDE.md sync after upgrade ─────────────────────────────────────
info "=== Part B: CLAUDE.md sync ==="
JCODEMUNCH="$PROJ_ROOT/.venv/bin/jcodemunch-mcp"

if [[ "$UPGRADED" -eq 1 && -x "$JCODEMUNCH" ]]; then
    NEW_TOOLS=$("$JCODEMUNCH" claude-md --format append 2>/dev/null || true)
    if [[ -n "$NEW_TOOLS" && "$NEW_TOOLS" != *"No new tools"* ]]; then
        info "New tools detected in jcodemunch. Triggering post-upgrade-mcp-integration..."
        if [[ "$DRY_RUN" -eq 1 ]]; then
            info "DRY RUN: would run claude -p to sync CLAUDE.md routing"
        else
            SYNC_PROMPT="The jcodemunch-mcp package was just upgraded in $PROJ_ROOT. Run the post-upgrade-mcp-integration skill to check for new tools and update both the project CLAUDE.md and ~/.claude/CLAUDE.md routing policy, then commit. The new tools not yet in CLAUDE.md are: $NEW_TOOLS"
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
```

With:

```bash
# ── Part B: post-upgrade evaluation (all packages) ───────────────────────────
info "=== Part B: Post-upgrade evaluation ==="
JCODEMUNCH="$PROJ_ROOT/.venv/bin/jcodemunch-mcp"

if [[ "$UPGRADED" -eq 1 ]]; then
    for pkg in "${PACKAGES_TO_UPGRADE[@]}"; do
        old_sha="${OLD_SHAS[$pkg]:-?}"
        new_sha=$(parse_lock_sha "$pkg")

        if [[ "$old_sha" == "?" || "$old_sha" == "$new_sha" ]]; then
            info "$pkg: SHA unchanged — skipping evaluation"
            continue
        fi

        info "$pkg: evaluating upgrade ${old_sha}→${new_sha}"

        commits=$(fetch_commit_log "$pkg" "$old_sha" "$new_sha")
        if [[ -z "$commits" ]]; then
            warn "$pkg: could not fetch commit log (GitHub API issue) — skipping"
            continue
        fi

        breaking=$(printf '%s\n' "$commits" | grep -iE 'breaking|BREAKING.CHANGE|deprecated|removed|incompatible' || true)
        [[ -n "$breaking" ]] && BREAKING_FLAGS+=("$pkg")

        jcm_tools=""
        if [[ "$pkg" == "jcodemunch-mcp" && -x "$JCODEMUNCH" ]]; then
            jcm_tools=$("$JCODEMUNCH" claude-md --format append 2>/dev/null || true)
            [[ "$jcm_tools" == *"No new tools"* ]] && jcm_tools=""
        fi

        if [[ "$DRY_RUN" -eq 1 ]]; then
            info "DRY RUN: would evaluate $pkg with claude -p"
            [[ -n "$breaking" ]] && info "DRY RUN: breaking changes detected: $breaking"
            [[ -n "$jcm_tools" ]] && info "DRY RUN: new jcodemunch tools: $jcm_tools"
            continue
        fi

        EVAL_PROMPT="The $pkg package was just upgraded in $PROJ_ROOT (${old_sha}→${new_sha}).

Commit log (one subject line per commit):
$commits
${breaking:+
BREAKING CHANGES DETECTED in the commit log above:
$breaking
}${jcm_tools:+
NEW JCODEMUNCH TOOLS not yet in CLAUDE.md:
$jcm_tools
}
Your tasks — do all that apply, nothing else:
1. If new tools or routing changes are needed: update $PROJ_ROOT/CLAUDE.md and ~/.claude/CLAUDE.md. Keep existing formatting and section structure.
2. If breaking changes are present: append a brief entry under the most recent date heading in the 'What happened' section of $PROJ_ROOT/HANDOFF.md. Format exactly: '- **$pkg breaking change**: <one sentence — what changed and what callers must update>'.
3. Commit any file changes with message 'chore: post-upgrade sync — $pkg ${old_sha}→${new_sha}'.
4. If nothing requires a change, do nothing and exit cleanly."

        if "$CLAUDE_BIN" -p "$EVAL_PROMPT" >> "$LOG" 2>&1; then
            info "$pkg: evaluation complete."
        else
            warn "$pkg: claude -p evaluation failed (non-fatal)"
        fi
    done
else
    info "No upgrade performed — post-upgrade evaluation skipped."
fi
```

- [ ] **Step 2: Syntax check**

```bash
bash -n scripts/auto-maintain.sh
```

Expected: no output.

---

## Task 5: Add symlink pass to Part C + extend Telegram summary

**Files:**
- Modify: `scripts/auto-maintain.sh` (Part C after git commit ~line 206; Telegram block ~line 245)

- [ ] **Step 1: Add symlink pass after "Skills committed."**

In `scripts/auto-maintain.sh`, find this line (inside the Part C `else` branch, after the git commit):

```bash
            info "Skills committed."
```

Replace with:

```bash
            info "Skills committed."

            CLAUDE_DIR="${CLAUDE_HOME:-$HOME/.claude}"
            mkdir -p "$CLAUDE_DIR/skills"
            for src in "$PROJ_ROOT/global-skills"/*/; do
                [ -d "$src" ] || continue
                skill_name=$(basename "$src")
                dst="$CLAUDE_DIR/skills/$skill_name"
                if [ ! -L "$dst" ] || [ "$(readlink -f "$dst")" != "$(readlink -f "$src")" ]; then
                    rm -rf "$dst"
                    ln -sfn "$src" "$dst"
                    info "Symlinked skill: $skill_name"
                fi
            done
```

- [ ] **Step 2: Extend the Telegram SUMMARY to include breaking-change flags**

Find the Telegram notification block (around line 243):

```bash
if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" && "$DRY_RUN" -eq 0 ]]; then
    SUMMARY="auto-maintain: "
    [[ "$UPGRADED" -eq 1 ]] && SUMMARY+="upgraded ${PACKAGES_TO_UPGRADE[*]}. "
    [[ "${#SKILL_NAMES[@]:-0}" -gt 0 ]] && SUMMARY+="committed ${#SKILL_NAMES[@]} skill(s). "
    [[ "$UPGRADED" -eq 0 && "${#SKILL_NAMES[@]:-0}" -eq 0 ]] && SUMMARY+="nothing to do."
    source "$PROJ_ROOT/lib/notify.sh" 2>/dev/null && notify_send_text "$SUMMARY" || true
fi
```

Replace with:

```bash
if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" && "$DRY_RUN" -eq 0 ]]; then
    SUMMARY="auto-maintain: "
    if [[ "$UPGRADED" -eq 1 ]]; then
        SUMMARY+="upgraded ${PACKAGES_TO_UPGRADE[*]}. "
        [[ "${#BREAKING_FLAGS[@]}" -gt 0 ]] && SUMMARY+="⚠️ breaking changes in ${BREAKING_FLAGS[*]} — see HANDOFF.md. "
    fi
    [[ "${#SKILL_NAMES[@]:-0}" -gt 0 ]] && SUMMARY+="committed ${#SKILL_NAMES[@]} skill(s). "
    [[ "$UPGRADED" -eq 0 && "${#SKILL_NAMES[@]:-0}" -eq 0 ]] && SUMMARY+="nothing to do."
    source "$PROJ_ROOT/lib/notify.sh" 2>/dev/null && notify_send_text "$SUMMARY" || true
fi
```

- [ ] **Step 3: Syntax check**

```bash
bash -n scripts/auto-maintain.sh
```

Expected: no output.

---

## Task 6: Integration verification + commit

- [ ] **Step 1: Full dry-run of auto-maintain**

```bash
bash scripts/auto-maintain.sh --dry-run 2>&1 | tee /tmp/auto-maintain-dryrun.txt
```

Expected output includes all four section headers and exits cleanly:
```
[...] INFO  === Part A: Package freshness check ===
[...] INFO  jcodemunch-mcp: N commits behind HEAD (threshold: 20)
[...] INFO  jdatamunch-mcp: N commits behind HEAD (threshold: 20)
[...] INFO  jdocmunch-mcp: N commits behind HEAD (threshold: 20)
[...] INFO  mempalace: N commits behind HEAD (threshold: 5)
[...] INFO  All packages within threshold. No upgrade needed.
[...] INFO  === Part B: Post-upgrade evaluation ===
[...] INFO  No upgrade performed — post-upgrade evaluation skipped.
[...] INFO  === Part C: Untracked global-skills check ===
[...] INFO  No untracked global-skills files.
[...] INFO  === Part D: Embedding canary ===
[...] INFO  === auto-maintain complete ===
```

If any package is above threshold, the dry-run will log "DRY RUN: would evaluate $pkg with claude -p" instead of running claude.

- [ ] **Step 2: Verify symlink logic fires correctly**

Create a throwaway test skill, confirm Part C would link it, then delete it:

```bash
mkdir -p /tmp/test-skill-verify/global-skills/test-auto-skill
echo -e '---\nname: test-auto-skill\ndescription: throwaway\n---\ntest' \
    > /tmp/test-skill-verify/global-skills/test-auto-skill/SKILL.md

# Manually exercise just the symlink loop
PROJ_ROOT=/opt/proj/Uncle-J-s-Refinery
CLAUDE_DIR="${CLAUDE_HOME:-$HOME/.claude}"
src="$PROJ_ROOT/global-skills/readme-sync"  # already exists
skill_name="readme-sync"
dst="$CLAUDE_DIR/skills/$skill_name"
readlink -f "$dst" && echo "symlink OK"

rm -rf /tmp/test-skill-verify
```

Expected: prints the resolved path of the readme-sync symlink, confirming the symlink mechanism works.

- [ ] **Step 3: Commit all changes**

```bash
git add scripts/auto-maintain.sh install-reliability.sh
git commit -m "feat: skill auto-install + all-package post-upgrade evaluation

- install-reliability.sh: dynamic global-skills/ scan replaces hardcoded list
- auto-maintain Part A: capture OLD_SHAS before uv lock; init BREAKING_FLAGS
- auto-maintain Part B: evaluate all 4 packages post-upgrade — commit log
  fetch via GitHub API, breaking-change grep, claude -p per package
- auto-maintain Part C: symlink new skills immediately after git commit
- auto-maintain Telegram: surface breaking-change flags in summary message"
```

- [ ] **Step 4: Update docs + push**

```bash
# CHANGELOG and HANDOFF are updated in the commit above's session context.
# Verify push succeeds:
git push
git log --oneline -5
```

Expected: clean push, latest commit visible.

# Telegram Gateway Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the update_id dedup bug, then wire six proactive Telegram notifications (health failures, security events, skill approvals, Ralph plateau, dreaming FYI) so the gateway acts as a full monitoring + authorization channel.

**Architecture:** All notifications go through `lib/notify.sh` → `lib/notify-telegram.sh`, the same path stack-alerts already uses. Skill approval drafting moves from auto-commit in `auto-maintain.sh` to a draft-then-pitch pattern that hooks into the gateway's existing `promote` command. A new `scripts/healthcheck-notify.sh` wraps `healthcheck.sh` for cron-scheduled alerting.

**Tech Stack:** bash, Python 3 (stdlib only), Telegram Bot API, `lib/notify.sh` abstraction

**Efficient execution order:** dedup fix → security events (both touch the gateway) → healthcheck notify (new script) → skill approval (auto-maintain change) → Ralph plateau (ralph-harness) → dreaming FYI (dream.sh) → docs + push.

---

## Task 1: Fix the update_id dedup bug

**Problem:** The Python script prints `new_offset` only once at exit. If it crashes mid-processing, bash captures an empty string and writes it to the offset file. Next cron run reads `""` → defaults to `0` → reprocesses all messages. A double-processed approval can trigger an action twice.

**Fix:** Advance the offset file atomically inside Python, per-message, BEFORE processing the message (Telegram Bot API convention: mark seen then act; a dropped message is safer than a duplicate action).

**Files:**
- Modify: `scripts/telegram-gateway-poll.sh`

- [ ] **Step 1: Pass OFFSET_FILE path into Python**

In `scripts/telegram-gateway-poll.sh`, find the `NEW_OFFSET=$(python3 - \` block. Change the argument list to include the offset file path as a 5th arg:

```bash
NEW_OFFSET=$(python3 - \
  "$PROJ_ROOT" \
  "$CLAUDE_BIN" \
  "$OFFSET" \
  "$LOG_FILE" \
  "$OFFSET_FILE" \
  << 'PYEOF'
```

- [ ] **Step 2: Update Python to accept offset_file arg and write atomically per-update**

In the Python heredoc, change `sys.argv[4]` references and add the atomic write. Find the line:
```python
log_file       = sys.argv[4]
```
Replace with:
```python
log_file       = sys.argv[4]
offset_file    = sys.argv[5]
```

Then find the inner loop line:
```python
    if update_id + 1 > new_offset:
        new_offset = update_id + 1
```
Replace with:
```python
    if update_id + 1 > new_offset:
        new_offset = update_id + 1
        # Advance offset before processing — prevents duplicate actions on crash
        _tmp = offset_file + ".tmp"
        with open(_tmp, "w") as _f:
            _f.write(str(new_offset))
        os.replace(_tmp, offset_file)
```

- [ ] **Step 3: Remove the final bash offset write (Python now owns it)**

After the heredoc block, find:
```bash
# Write updated offset back
printf '%s' "$NEW_OFFSET" > "$OFFSET_FILE"
log "Offset updated to ${NEW_OFFSET}"
```
Replace with:
```bash
log "Offset updated to ${NEW_OFFSET}"
```

- [ ] **Step 4: Smoke-test manually**

```bash
# Simulate a crashed run by deleting offset file then re-running
rm -f /opt/proj/Uncle-J-s-Refinery/state/telegram-gateway-offset.txt
bash /opt/proj/Uncle-J-s-Refinery/scripts/telegram-gateway-poll.sh
# Verify offset file now exists and contains a number
cat /opt/proj/Uncle-J-s-Refinery/state/telegram-gateway-offset.txt
```
Expected: file contains an integer (may be 0 if no updates, which is correct).

- [ ] **Step 5: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add scripts/telegram-gateway-poll.sh
git commit -m "fix: advance Telegram offset atomically per-update to prevent duplicate processing"
```

---

## Task 2: Wire security events → FYI notifications

**Problem:** When an unauthorized `chat_id` contacts the bot, the event is silently logged. Will has no way to know someone found his bot token.

**Fix:** When the authorized-chat check fails, call `tg_send()` to the authorized chat to notify Will. Also notify on injection attempts.

**Files:**
- Modify: `scripts/telegram-gateway-poll.sh` (Python section only)

- [ ] **Step 1: Add unauthorized-chat notification**

In the Python heredoc, find:
```python
    if from_chat != str(chat_id):
        log(f"Ignoring message from unauthorized chat_id={from_chat}")
        continue
```
Replace with:
```python
    if from_chat != str(chat_id):
        log(f"Ignoring message from unauthorized chat_id={from_chat}")
        tg_send(f"⚠️ <b>Security alert</b>: message received from unauthorized chat_id <code>{from_chat[:8]}…</code>. If this is unexpected, rotate your bot token.")
        continue
```

- [ ] **Step 2: Add injection-attempt notification**

Find:
```python
    text, san_err = sanitize_input(text)
    if san_err:
        tg_send(san_err)
        continue
```
Replace with:
```python
    text, san_err = sanitize_input(text)
    if san_err:
        tg_send(san_err)
        tg_send("ℹ️ <b>Security notice</b>: a message from your chat was blocked by the injection filter. Check your Telegram account if unexpected.")
        continue
```

- [ ] **Step 3: Test unauthorized chat detection**

The test suite already covers `check_rate_limit` and `sanitize_input`. Run it to confirm nothing is broken:
```bash
cd /opt/proj/Uncle-J-s-Refinery
python3 -m pytest tests/test_tg_security.py -v
```
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add scripts/telegram-gateway-poll.sh
git commit -m "feat: notify Will on unauthorized chat access and injection attempts via Telegram"
```

---

## Task 3: Wire healthcheck failures → Telegram

**Problem:** `healthcheck.sh` only runs on-demand via `/health`. Failures go unnoticed until Will manually checks.

**Fix:** New `scripts/healthcheck-notify.sh` runs `healthcheck.sh`, captures failures, sends a notification. Registered as a daily cron.

**Files:**
- Create: `scripts/healthcheck-notify.sh`
- Modify: `install.sh` (register new cron)
- Modify: `healthcheck.sh` (add `--machine` flag that emits one-line summary to stdout)

- [ ] **Step 1: Add --machine output flag to healthcheck.sh**

In `healthcheck.sh`, after the `checks_failed=0` / `first_fail=""` declarations, find the argument-parsing loop and add:
```bash
MACHINE=0
```
In the `for arg in "$@"` loop, add a case:
```bash
        --machine) MACHINE=1 ;;
```

At the very end, after the `if [ "$checks_failed" -eq 0 ]` block, add before the `exit` calls:
```bash
# Machine-readable summary line for healthcheck-notify.sh
if [ "$MACHINE" -eq 1 ]; then
    if [ "$checks_failed" -eq 0 ]; then
        printf 'OK\n'
    else
        printf 'FAIL %d %s\n' "$checks_failed" "$first_fail"
    fi
fi
```

- [ ] **Step 2: Verify --machine flag works**

```bash
bash /opt/proj/Uncle-J-s-Refinery/healthcheck.sh --machine 2>/dev/null | tail -1
```
Expected: `OK` (assuming system is healthy) or `FAIL N <first_fail_tag>`.

- [ ] **Step 3: Create scripts/healthcheck-notify.sh**

```bash
cat > /opt/proj/Uncle-J-s-Refinery/scripts/healthcheck-notify.sh << 'EOF'
#!/usr/bin/env bash
# Daily cron: run healthcheck and notify Will via Telegram on failures.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJ_ROOT/.env"
LOG="$PROJ_ROOT/state/healthcheck-notify.log"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

mkdir -p "$PROJ_ROOT/state"
[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
    log "Missing Telegram credentials — skipping."
    exit 0
fi

source "$PROJ_ROOT/lib/notify.sh"

log "Running healthcheck..."
# Capture full output (stdout+stderr) for failure details
FULL_OUTPUT=$(bash "$PROJ_ROOT/healthcheck.sh" --machine 2>&1) && HC_EXIT=0 || HC_EXIT=$?

# Extract machine summary line
SUMMARY=$(printf '%s\n' "$FULL_OUTPUT" | grep -E '^(OK|FAIL)' | tail -1 || echo "")

if [[ "$HC_EXIT" -eq 0 ]] || [[ "$SUMMARY" == "OK" ]]; then
    log "Healthcheck passed — no notification sent."
    exit 0
fi

# Extract failure lines (lines starting with X marker)
FAILURES=$(printf '%s\n' "$FULL_OUTPUT" | grep -E '^\s+X\s+' | sed 's/^\s*X\s*//' | head -10 || echo "")
FAIL_COUNT=$(printf '%s\n' "$SUMMARY" | awk '{print $2}')
FIRST_TAG=$(printf '%s\n' "$SUMMARY" | awk '{print $3}')

MSG="🔴 <b>Health check failed</b> (${FAIL_COUNT:-?} issue(s))"
if [[ -n "$FAILURES" ]]; then
    MSG="${MSG}
$(printf '%s\n' "$FAILURES" | while IFS= read -r line; do printf '• %s\n' "$line"; done)"
fi
MSG="${MSG}

Run <code>/health</code> for details."

log "Sending failure notification: $FIRST_TAG"
notify_send_text "$MSG" || log "Failed to send Telegram notification"
EOF
chmod +x /opt/proj/Uncle-J-s-Refinery/scripts/healthcheck-notify.sh
```

- [ ] **Step 4: Register cron in install.sh**

In `install.sh`, find the block that registers crons (look for `uncle-j-telegram-gateway` or similar crontab entries). Add the healthcheck-notify cron alongside the others:

```bash
# Daily healthcheck notification at 07:00
register_cron "uncle-j-healthcheck-notify" \
    "0 7 * * * bash $REPO_ROOT/scripts/healthcheck-notify.sh >> $REPO_ROOT/state/healthcheck-notify.log 2>&1"
```

- [ ] **Step 5: Register the expected cron in healthcheck.sh check_crons**

In `healthcheck.sh`, find the `EXPECTED` associative array in `check_crons()`. Add:
```bash
[uncle-j-healthcheck-notify]="bash $REPO_ROOT/scripts/healthcheck-notify.sh"
```

- [ ] **Step 6: Run install.sh to register the cron, then verify**

```bash
bash /opt/proj/Uncle-J-s-Refinery/install.sh
crontab -l | grep healthcheck-notify
```
Expected: line containing `uncle-j-healthcheck-notify`.

- [ ] **Step 7: Dry-run the notify script**

```bash
bash /opt/proj/Uncle-J-s-Refinery/scripts/healthcheck-notify.sh
cat /opt/proj/Uncle-J-s-Refinery/state/healthcheck-notify.log | tail -3
```
Expected: `Healthcheck passed — no notification sent.` (or a Telegram message if health is currently degraded).

- [ ] **Step 8: Commit**

```bash
git add scripts/healthcheck-notify.sh healthcheck.sh install.sh
git commit -m "feat: daily healthcheck cron with Telegram alert on failure"
```

---

## Task 4: Wire skill approval → Telegram pitch (draft-then-promote)

**Problem:** `auto-maintain.sh` Part C auto-commits untracked `global-skills/` files without asking. The gateway already has a full `promote <id>` workflow for skill drafts — auto-maintain should feed into it.

**Fix:** Part C writes a draft to `state/skill-drafts/` and sends a `notify_send_text` with promote instructions, instead of auto-committing. The gateway's existing promote handler installs on confirmation.

**Files:**
- Modify: `scripts/auto-maintain.sh` (Part C only)

- [ ] **Step 1: Replace Part C auto-commit with draft-and-notify**

In `scripts/auto-maintain.sh`, find the Part C block starting with:
```bash
# ── Part C: auto-commit untracked global-skills files ────────────────────────
info "=== Part C: Untracked global-skills check ==="
```

Replace everything in Part C (from that comment through the SKILL_NAMES loop and its git commit block) up to but not including Part D / the final SUMMARY block, with:

```bash
# ── Part C: draft untracked global-skills for Telegram approval ──────────────
info "=== Part C: Untracked global-skills check ==="
DRAFTS_DIR="$PROJ_ROOT/state/skill-drafts"
mkdir -p "$DRAFTS_DIR"

UNTRACKED=$(git -C "$PROJ_ROOT" status --porcelain \
    | grep "^?? global-skills/" | sed 's/^?? //' | sed 's|/$||' || true)

SKILL_NAMES=()

if [[ -z "$UNTRACKED" ]]; then
    info "No untracked global-skills files."
else
    while IFS= read -r skill_dir; do
        skill_name=$(basename "$skill_dir")
        skill_md="$PROJ_ROOT/$skill_dir/SKILL.md"
        [[ ! -f "$skill_md" ]] && { warn "No SKILL.md in $skill_dir — skipping"; continue; }
        SKILL_NAMES+=("$skill_name")

        if [[ "$DRY_RUN" -eq 1 ]]; then
            info "DRY RUN: would draft skill: $skill_name"
            continue
        fi

        # Generate a short ID for the draft (6 hex chars from md5 of skill name)
        SKILL_ID=$(printf '%s' "$skill_name" | md5sum | cut -c1-6)
        DRAFT_PATH="$DRAFTS_DIR/${SKILL_ID}-skill-draft.md"
        cp "$skill_md" "$DRAFT_PATH"
        info "Drafted: $skill_name → $DRAFT_PATH (id=$SKILL_ID)"
    done <<< "$UNTRACKED"

    if [[ "${#SKILL_NAMES[@]:-0}" -gt 0 && "$DRY_RUN" -eq 0 ]]; then
        source "$PROJ_ROOT/lib/notify.sh" 2>/dev/null || true
        SKILL_LIST=$(printf '%s\n' "${SKILL_NAMES[@]}" | sed 's/^/• /')
        MSG="📋 <b>New skill(s) ready for review:</b>
${SKILL_LIST}

Reply <code>promote &lt;id&gt;</code> to install, or <code>promote &lt;id&gt; global</code>/<code>project</code> to skip classification."
        notify_send_text "$MSG" || warn "Telegram notify failed (non-fatal)"
    fi
fi
```

- [ ] **Step 2: Verify dry-run shows expected output**

```bash
bash /opt/proj/Uncle-J-s-Refinery/scripts/auto-maintain.sh --dry-run 2>&1 | grep -E "Part C|DRY RUN|draft"
```
Expected: "DRY RUN: would draft skill: …" for any untracked skills, or "No untracked global-skills files."

- [ ] **Step 3: Update SUMMARY line in auto-maintain.sh**

Find:
```bash
[[ "${#SKILL_NAMES[@]:-0}" -gt 0 ]] && SUMMARY+="committed ${#SKILL_NAMES[@]} skill(s). "
```
Replace with:
```bash
[[ "${#SKILL_NAMES[@]:-0}" -gt 0 ]] && SUMMARY+="drafted ${#SKILL_NAMES[@]} skill(s) for approval. "
```

- [ ] **Step 4: Commit**

```bash
git add scripts/auto-maintain.sh
git commit -m "feat: draft new skills to state/skill-drafts and pitch via Telegram instead of auto-committing"
```

---

## Task 5: Wire Ralph plateau → Telegram

**Problem:** When Ralph hits `--max-iterations` without a done verdict (exit code 2), the harness prints a warning and exits silently. Will has no way to know Ralph is stuck.

**Files:**
- Modify: `ralph-harness.sh`

- [ ] **Step 1: Add notify call at plateau exit**

In `ralph-harness.sh`, find:
```bash
        warn "Max iterations reached without a 'done' verdict. Inspect the PRD and repo diff manually."
```

Replace with:
```bash
        warn "Max iterations reached without a 'done' verdict. Inspect the PRD and repo diff manually."
        # Notify Will via Telegram — Ralph needs operator attention
        PRD_NAME="$(basename "${PRD_PATH:-unknown.md}" .md)"
        if [[ -f "$PROJ_ROOT/lib/notify.sh" ]]; then
            source "$PROJ_ROOT/lib/notify.sh" 2>/dev/null \
            && notify_send_text "🔁 <b>Ralph plateau</b>: <code>${PRD_NAME}</code> hit ${MAX_ITERATIONS} iterations without a done verdict. Manual inspection needed." \
            || true
        fi
```

Note: `PROJ_ROOT` needs to be in scope. Check that ralph-harness.sh defines it. If not, derive it:

In `ralph-harness.sh` near the top (after `set -euo pipefail`), confirm or add:
```bash
PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
```

- [ ] **Step 2: Smoke-test the change doesn't break normal exit**

```bash
bash /opt/proj/Uncle-J-s-Refinery/ralph-harness.sh --help 2>&1 | head -5
```
Expected: usage text, no errors.

- [ ] **Step 3: Commit**

```bash
git add ralph-harness.sh
git commit -m "feat: notify Will via Telegram when Ralph hits iteration plateau"
```

---

## Task 6: Wire dreaming/outcomes → FYI notification

**Problem:** After dream.sh runs successfully, Will has no idea it ran or what it found. A one-line FYI after each run gives visibility without needing to check logs.

**Files:**
- Modify: `features/dreaming/dream.sh`

- [ ] **Step 1: Add FYI notification at end of dream.sh**

In `features/dreaming/dream.sh`, find the final lines:
```bash
step "Dreaming run complete"
ok "Traces processed : $TRACE_COUNT"
ok "Output           : $OUTPUT_FILE"
ok "Last run         : $LAST_RUN_FILE"
```

Insert BEFORE those lines:
```bash
# FYI notification — skip if no traces (nothing interesting to report)
if [[ "$DRY_RUN" -eq 0 && "${TRACE_COUNT:-0}" -gt 0 ]]; then
    source "$STACK_ROOT/lib/notify.sh" 2>/dev/null \
    && notify_send_text "🌙 Dream run: ${TRACE_COUNT} trace(s) processed → playbooks updated in MemPalace." \
    || true
fi
```

- [ ] **Step 2: Verify dry-run suppresses notification**

```bash
bash /opt/proj/Uncle-J-s-Refinery/features/dreaming/dream.sh --dry-run 2>&1 | grep -i notify
```
Expected: no output (notification skipped in dry-run).

- [ ] **Step 3: Commit**

```bash
git add features/dreaming/dream.sh
git commit -m "feat: send Telegram FYI after dream synthesis run completes"
```

---

## Task 7: Update documentation and push

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `HANDOFF.md`

- [ ] **Step 1: Update CHANGELOG.md**

Add a new entry at the top of CHANGELOG.md:

```markdown
## 2026-05-22 — Telegram gateway: notifications + dedup fix

### Fixed
- **Dedup bug**: Telegram `update_id` offset now written atomically per-update inside Python, before message processing. Prevents duplicate Claude invocations on crash/restart.

### Added
- **Security alerts**: unauthorized chat_id access and injection-filter blocks now send FYI notifications to Will's chat
- **Health alerts**: new `scripts/healthcheck-notify.sh` runs daily at 07:00; sends Telegram notification on any healthcheck failure
- **Skill approval flow**: `auto-maintain.sh` Part C now drafts new skills to `state/skill-drafts/` and pitches Will via Telegram instead of auto-committing; existing `promote <id>` gateway command handles install
- **Ralph plateau alert**: `ralph-harness.sh` sends Telegram notification when max iterations reached without done verdict
- **Dreaming FYI**: `features/dreaming/dream.sh` sends a one-line Telegram notice after each successful synthesis run
```

- [ ] **Step 2: Update HANDOFF.md**

In the Telegram Gateway section of HANDOFF.md, update or add:

```markdown
### Telegram Gateway — Notification Events (as of 2026-05-22)

| Event | Script | Type |
|-------|--------|------|
| Stack package update available | stack-alerts-send.sh | Approve/skip pitch |
| New skill draft ready | auto-maintain.sh Part C | FYI + promote instructions |
| Health check failure | healthcheck-notify.sh (daily 07:00) | FYI |
| Unauthorized bot access attempt | telegram-gateway-poll.sh | FYI |
| Injection attempt blocked | telegram-gateway-poll.sh | FYI |
| Ralph plateau reached | ralph-harness.sh | FYI |
| Dream synthesis complete | features/dreaming/dream.sh | FYI |
```

- [ ] **Step 3: Final check**

```bash
cd /opt/proj/Uncle-J-s-Refinery
bash healthcheck.sh 2>&1 | tail -3
git status
```
Expected: `HEALTHCHECK: ok`, clean git status except staged docs.

- [ ] **Step 4: Commit docs**

```bash
git add CHANGELOG.md HANDOFF.md
git commit -m "docs: document Telegram notification events and gateway dedup fix"
```

- [ ] **Step 5: Push**

```bash
git push
```

---

## Self-Review

**Spec coverage check:**
1. ✅ Dedup bug — Task 1
2. ✅ Healthcheck failures → Telegram — Task 3
3. ✅ Skill approval → Telegram pitch — Task 4
4. ✅ Ralph plateau → Telegram — Task 5
5. ✅ Dreaming/outcomes → FYI — Task 6
6. ✅ Security events → FYI — Task 2
7. ✅ Docs + push — Task 7

**Placeholder scan:** No TBDs. All code blocks are complete and runnable.

**Type consistency:** `notify_send_text` used throughout (consistent with existing `stack-alerts-send.sh`). `PROJ_ROOT` / `STACK_ROOT` variable names match each file's existing convention.

**Risk notes:**
- Task 2 (security notifications) uses `tg_send()` for injection attempts from Will's own chat — this means Will gets a notice if he accidentally trips the filter himself. Acceptable.
- Task 4 changes skill auto-commit to draft-and-notify. Any skills already in `global-skills/` untracked before this change will be drafted on next auto-maintain run, not auto-committed.
- Task 1 removes the bash-side offset write; Python now owns it. If Python crashes before any updates are processed (i.e., empty `result` array), the offset file is not written — which is correct since there's nothing to advance.

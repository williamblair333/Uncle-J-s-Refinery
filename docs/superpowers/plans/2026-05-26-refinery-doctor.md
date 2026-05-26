# Refinery Doctor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `scripts/refinery-doctor.sh` — a standalone config-drift detection and repair script with 4 day-1 migration checks and a safe `--fix` mode using atomic writes.

**Architecture:** Single bash script mirroring `healthcheck.sh` style (step/ok/bad/hint helpers, `record_fail`, `--fix` flag). Each migration is a `check_*` function. `--fix` applies auto-fixable migrations atomically. Exit 0 = clean, exit 1 = pending migrations.

**Tech Stack:** Bash, `sha256sum`/`shasum`, `claude mcp list` (for scope check)

---

### Task 1: Skeleton with arg parsing and output helpers

**Files:**
- Create: `scripts/refinery-doctor.sh`

- [ ] **Step 1: Create the script skeleton**

```bash
#!/usr/bin/env bash
# refinery-doctor.sh — config schema drift detection and repair.
#
# Checks for .env key renames, stale MCP scopes, CLAUDE.md drift,
# and placeholder values. Distinct from healthcheck.sh (runtime health).
#
# Usage:
#   bash scripts/refinery-doctor.sh            # dry-run: report only
#   bash scripts/refinery-doctor.sh --fix      # apply auto-fixable migrations
#   bash scripts/refinery-doctor.sh --check embed-model  # one check only
#
# Exit: 0 if all clean, 1 if pending migrations.
# Final stdout line: DOCTOR: ok  or  DOCTOR: N migration(s) available

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

FIX_MODE=false
ONLY_CHECK=""

for arg in "$@"; do
    case "$arg" in
        --fix)   FIX_MODE=true ;;
        --check) ;;  # next arg handled below
        *)
            if [[ "${PREV_ARG:-}" == "--check" ]]; then
                ONLY_CHECK="$arg"
            fi
            ;;
    esac
    PREV_ARG="$arg"
done

step()       { printf '\n==> %s\n' "$*" >&2; }
ok()         { printf '    OK  %s\n' "$*" >&2; }
migration()  { printf '    MIGRATION AVAILABLE  %s\n' "$*" >&2; }
fixed()      { printf '    FIXED  %s\n' "$*" >&2; }
info()       { printf '    INFO  %s\n' "$*" >&2; }
suggest()    { printf '        fix: %s\n' "$*" >&2; }

migrations_pending=0
first_pending=""

record_migration() {
    migrations_pending=$((migrations_pending + 1))
    [[ -z "$first_pending" ]] && first_pending="$1"
}
```

- [ ] **Step 2: Add atomic write helper and final summary**

Append to the script:

```bash
# Atomic .env write: backup → write to tmp → rename
# Usage: atomic_env_write <new_content_string>
atomic_env_write() {
    local new_content="$1"
    cp "$ENV_FILE" "${ENV_FILE}.bak"
    printf '%s' "$new_content" > "${ENV_FILE}.tmp"
    mv "${ENV_FILE}.tmp" "$ENV_FILE"
}

# ── run checks ──────────────────────────────────────────────────────────────

run_check() {
    local name="$1"
    [[ -n "$ONLY_CHECK" && "$ONLY_CHECK" != "$name" ]] && return
    "check_${name//-/_}"
}

# placeholder — checks defined in tasks 2-5
check_embed_model()      { :; }
check_jcodemunch_scope() { :; }
check_claude_md_sync()   { :; }
check_env_placeholders() { :; }

run_check embed-model
run_check jcodemunch-scope
run_check claude-md-sync
run_check env-placeholders

# ── summary ─────────────────────────────────────────────────────────────────

printf '\n'
if [[ "$migrations_pending" -eq 0 ]]; then
    printf 'DOCTOR: ok\n'
    exit 0
else
    if [[ "$FIX_MODE" == true ]]; then
        printf 'DOCTOR: %d migration(s) applied\n' "$migrations_pending"
    else
        printf 'DOCTOR: %d migration(s) available (run --fix to apply)\n' "$migrations_pending"
    fi
    exit 1
fi
```

- [ ] **Step 3: Make executable and verify it runs**

```bash
chmod +x /opt/proj/Uncle-J-s-Refinery/scripts/refinery-doctor.sh
bash /opt/proj/Uncle-J-s-Refinery/scripts/refinery-doctor.sh
```

Expected output ends with: `DOCTOR: ok` (all stub checks pass)

- [ ] **Step 4: Commit skeleton**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git checkout -b feat/refinery-doctor
git add scripts/refinery-doctor.sh
git commit -m "feat: add refinery-doctor.sh skeleton with arg parsing and output helpers"
```

---

### Task 2: check_embed_model — JCODEMUNCH_EMBED_MODEL in .env

**Files:**
- Modify: `scripts/refinery-doctor.sh` (replace stub `check_embed_model`)

- [ ] **Step 1: Replace the stub with the real check**

Replace `check_embed_model()      { :; }` with:

```bash
check_embed_model() {
    step "embed-model — JCODEMUNCH_EMBED_MODEL in .env"
    if [[ ! -f "$ENV_FILE" ]]; then
        info ".env not found — skipping"
        return
    fi
    if grep -q '^JCODEMUNCH_EMBED_MODEL=' "$ENV_FILE" 2>/dev/null; then
        ok "already set"
        return
    fi
    # Key missing — find model path
    local model_path="$HOME/.code-index/models/all-MiniLM-L6-v2"
    if [[ ! -d "$model_path" ]]; then
        migration "JCODEMUNCH_EMBED_MODEL missing from .env and model not found at $model_path"
        suggest "download model first: bash $REPO_ROOT/scripts/download-model.sh"
        record_migration "embed-model"
        return
    fi
    migration "JCODEMUNCH_EMBED_MODEL missing from .env (model present at $model_path)"
    suggest "append: echo 'JCODEMUNCH_EMBED_MODEL=all-MiniLM-L6-v2' >> $ENV_FILE"
    record_migration "embed-model"
    if [[ "$FIX_MODE" == true ]]; then
        local current
        current="$(cat "$ENV_FILE")"
        # Ensure file ends with newline before appending
        [[ "${current: -1}" != $'\n' ]] && current+=$'\n'
        current+="JCODEMUNCH_EMBED_MODEL=all-MiniLM-L6-v2"$'\n'
        atomic_env_write "$current"
        fixed "appended JCODEMUNCH_EMBED_MODEL=all-MiniLM-L6-v2 to .env (backup: .env.bak)"
    fi
}
```

- [ ] **Step 2: Test on this machine (key already present)**

```bash
bash /opt/proj/Uncle-J-s-Refinery/scripts/refinery-doctor.sh --check embed-model
```

Expected:
```
==> embed-model — JCODEMUNCH_EMBED_MODEL in .env
    OK  already set
```

- [ ] **Step 3: Test detection by temporarily commenting the key**

```bash
# Temporarily rename key in a copy to test detection path
grep -v '^JCODEMUNCH_EMBED_MODEL=' /opt/proj/Uncle-J-s-Refinery/.env > /tmp/test-env-no-model
JCODEMUNCH_EMBED_MODEL_BACKUP=$(grep '^JCODEMUNCH_EMBED_MODEL=' /opt/proj/Uncle-J-s-Refinery/.env)
cp /opt/proj/Uncle-J-s-Refinery/.env /opt/proj/Uncle-J-s-Refinery/.env.testbak
cp /tmp/test-env-no-model /opt/proj/Uncle-J-s-Refinery/.env

bash /opt/proj/Uncle-J-s-Refinery/scripts/refinery-doctor.sh --check embed-model
# Expected: MIGRATION AVAILABLE

# Restore
cp /opt/proj/Uncle-J-s-Refinery/.env.testbak /opt/proj/Uncle-J-s-Refinery/.env
rm /opt/proj/Uncle-J-s-Refinery/.env.testbak
```

- [ ] **Step 4: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add scripts/refinery-doctor.sh
git commit -m "feat(doctor): add check_embed_model — JCODEMUNCH_EMBED_MODEL in .env"
```

---

### Task 3: check_jcodemunch_scope — stale MCP registration

**Files:**
- Modify: `scripts/refinery-doctor.sh` (replace stub `check_jcodemunch_scope`)

- [ ] **Step 1: Replace the stub**

Replace `check_jcodemunch_scope() { :; }` with:

```bash
check_jcodemunch_scope() {
    step "jcodemunch-scope — MCP registration scope"
    if ! command -v claude &>/dev/null; then
        info "claude binary not found — skipping"
        return
    fi
    local mcp_list
    mcp_list=$(claude mcp list 2>/dev/null) || { info "claude mcp list failed — skipping"; return; }

    local stale_scopes=()
    for scope in local project; do
        # claude mcp list output format: "jcodemunch  <scope>  <path>"
        if echo "$mcp_list" | grep -qiE "jcodemunch.*\b${scope}\b"; then
            stale_scopes+=("$scope")
        fi
    done

    if [[ "${#stale_scopes[@]}" -eq 0 ]]; then
        ok "jcodemunch not registered at local/project scope"
        return
    fi

    migration "jcodemunch registered at stale scope(s): ${stale_scopes[*]}"
    for scope in "${stale_scopes[@]}"; do
        suggest "run: claude mcp remove jcodemunch -s $scope"
    done
    record_migration "jcodemunch-scope"

    if [[ "$FIX_MODE" == true ]]; then
        for scope in "${stale_scopes[@]}"; do
            claude mcp remove jcodemunch -s "$scope" 2>/dev/null \
                && fixed "removed jcodemunch from $scope scope" \
                || info "claude mcp remove jcodemunch -s $scope exited non-zero"
        done
    fi
}
```

- [ ] **Step 2: Test (clean machine — should report OK)**

```bash
bash /opt/proj/Uncle-J-s-Refinery/scripts/refinery-doctor.sh --check jcodemunch-scope
```

Expected: `OK  jcodemunch not registered at local/project scope`

- [ ] **Step 3: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add scripts/refinery-doctor.sh
git commit -m "feat(doctor): add check_jcodemunch_scope — stale MCP registration"
```

---

### Task 4: check_claude_md_sync — ~/.claude/CLAUDE.md drift

**Files:**
- Modify: `scripts/refinery-doctor.sh` (replace stub `check_claude_md_sync`)

- [ ] **Step 1: Replace the stub**

Replace `check_claude_md_sync() { :; }` with:

```bash
check_claude_md_sync() {
    step "claude-md-sync — ~/.claude/CLAUDE.md vs repo CLAUDE.md"
    local repo_src="$REPO_ROOT/CLAUDE.md"
    local installed="$HOME/.claude/CLAUDE.md"

    if [[ ! -f "$repo_src" ]]; then
        info "repo CLAUDE.md not found — skipping"
        return
    fi
    if [[ ! -f "$installed" ]]; then
        migration "~/.claude/CLAUDE.md not present"
        suggest "run: cp $repo_src $installed"
        record_migration "claude-md-sync"
        if [[ "$FIX_MODE" == true ]]; then
            cp "$repo_src" "$installed"
            fixed "copied $repo_src → $installed"
        fi
        return
    fi

    # Compare checksums (sha256sum on Linux, shasum on macOS)
    local sum_cmd
    if command -v sha256sum &>/dev/null; then
        sum_cmd="sha256sum"
    elif command -v shasum &>/dev/null; then
        sum_cmd="shasum -a 256"
    else
        info "no sha256 tool found — skipping sync check"
        return
    fi

    local repo_sum installed_sum
    repo_sum=$($sum_cmd "$repo_src" | awk '{print $1}')
    installed_sum=$($sum_cmd "$installed" | awk '{print $1}')

    if [[ "$repo_sum" == "$installed_sum" ]]; then
        ok "in sync"
        return
    fi

    migration "~/.claude/CLAUDE.md differs from repo (repo: ${repo_sum:0:12}… installed: ${installed_sum:0:12}…)"
    suggest "run: cp $repo_src $installed   # backs up to $installed.bak first"
    record_migration "claude-md-sync"

    if [[ "$FIX_MODE" == true ]]; then
        cp "$installed" "${installed}.bak"
        cp "$repo_src" "$installed"
        fixed "updated ~/.claude/CLAUDE.md (backup: ${installed}.bak)"
    fi
}
```

- [ ] **Step 2: Test (should report OK — files should match)**

```bash
bash /opt/proj/Uncle-J-s-Refinery/scripts/refinery-doctor.sh --check claude-md-sync
```

Expected: `OK  in sync`

- [ ] **Step 3: Test drift detection**

```bash
echo "# drift test" >> /tmp/claude-md-drift-test
# Temporarily make installed copy differ
cp ~/.claude/CLAUDE.md ~/.claude/CLAUDE.md.testbak
echo "# drift" >> ~/.claude/CLAUDE.md
bash /opt/proj/Uncle-J-s-Refinery/scripts/refinery-doctor.sh --check claude-md-sync
# Expected: MIGRATION AVAILABLE
cp ~/.claude/CLAUDE.md.testbak ~/.claude/CLAUDE.md
rm ~/.claude/CLAUDE.md.testbak
```

- [ ] **Step 4: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add scripts/refinery-doctor.sh
git commit -m "feat(doctor): add check_claude_md_sync — ~/.claude/CLAUDE.md drift"
```

---

### Task 5: check_env_placeholders — template values in .env

**Files:**
- Modify: `scripts/refinery-doctor.sh` (replace stub `check_env_placeholders`)

- [ ] **Step 1: Replace the stub**

Replace `check_env_placeholders() { :; }` with:

```bash
check_env_placeholders() {
    step "env-placeholders — template values in .env"
    if [[ ! -f "$ENV_FILE" ]]; then
        info ".env not found — skipping"
        return
    fi
    # Patterns that indicate a value was never filled in
    local placeholder_patterns=('your-' 'changeme' 'PLACEHOLDER' 'TODO' 'xxx' 'example\.com' '<your')
    local found_lines=()
    for pattern in "${placeholder_patterns[@]}"; do
        while IFS= read -r line; do
            # Skip comment lines
            [[ "$line" =~ ^[[:space:]]*# ]] && continue
            [[ -z "${line// }" ]] && continue
            found_lines+=("$line")
        done < <(grep -iE "$pattern" "$ENV_FILE" 2>/dev/null || true)
    done

    if [[ "${#found_lines[@]}" -eq 0 ]]; then
        ok "no placeholder values detected"
        return
    fi

    migration "${#found_lines[@]} line(s) look like unfilled template placeholders"
    for line in "${found_lines[@]}"; do
        # Show key name only — never log values
        local key="${line%%=*}"
        suggest "review: $key  (value looks like a placeholder)"
    done
    record_migration "env-placeholders"
    info "this check is report-only — fill in real values manually"
}
```

- [ ] **Step 2: Test (should report OK on this machine)**

```bash
bash /opt/proj/Uncle-J-s-Refinery/scripts/refinery-doctor.sh --check env-placeholders
```

Expected: `OK  no placeholder values detected`

- [ ] **Step 3: Run all checks together**

```bash
bash /opt/proj/Uncle-J-s-Refinery/scripts/refinery-doctor.sh
```

Expected: `DOCTOR: ok`

- [ ] **Step 4: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add scripts/refinery-doctor.sh
git commit -m "feat(doctor): add check_env_placeholders — template values in .env"
```

---

### Task 6: Wire into install-reliability.sh and smoke test --fix

**Files:**
- Modify: `scripts/refinery-doctor.sh` (fix `--check` arg parsing bug)
- Modify: `install-reliability.sh` (add mention in usage comments)

- [ ] **Step 1: Fix --check arg parsing (PREV_ARG pattern is fragile)**

The skeleton used a fragile `PREV_ARG` approach. Replace the arg parsing block with:

```bash
FIX_MODE=false
ONLY_CHECK=""
i=1
while [[ $i -le $# ]]; do
    arg="${!i}"
    case "$arg" in
        --fix)   FIX_MODE=true ;;
        --check)
            i=$((i + 1))
            ONLY_CHECK="${!i:-}"
            ;;
        -h|--help)
            sed -n '1,10p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) printf 'Unknown arg: %s\n' "$arg" >&2; exit 2 ;;
    esac
    i=$((i + 1))
done
```

- [ ] **Step 2: Verify --check still works after fix**

```bash
bash /opt/proj/Uncle-J-s-Refinery/scripts/refinery-doctor.sh --check embed-model
```

Expected: `OK  already set`

- [ ] **Step 3: Verify --fix dry-run on clean machine (all OK, no changes)**

```bash
bash /opt/proj/Uncle-J-s-Refinery/scripts/refinery-doctor.sh --fix
```

Expected: `DOCTOR: 0 migration(s) applied` (since all checks pass, exit 0)

Wait — when `--fix` is passed and there are 0 migrations, the current summary says `DOCTOR: 0 migration(s) applied` but exits 0. That's correct. Verify this works.

- [ ] **Step 4: Add a mention to install-reliability.sh header comments**

In `install-reliability.sh`, find the comment block at the top and append after the last comment line before `set -euo pipefail`:

```bash
# Config drift: bash scripts/refinery-doctor.sh [--fix]
```

- [ ] **Step 5: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add scripts/refinery-doctor.sh install-reliability.sh
git commit -m "feat(doctor): fix --check arg parsing, wire mention into install-reliability.sh"
```

---

### Task 7: PR

- [ ] **Step 1: Push branch**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git push -u origin feat/refinery-doctor
```

- [ ] **Step 2: Create PR (invoke pre-mortem first)**

Run the `pre-mortem` skill before creating the PR, then:

```bash
gh pr create \
  --title "feat: add refinery-doctor config drift detection and repair" \
  --body "$(cat <<'EOF'
## What does this PR do

Adds `scripts/refinery-doctor.sh` — a new standalone script for config schema drift detection and repair. Inspired by the `openclaw doctor --fix` pattern from competitive analysis.

**Distinct from `healthcheck.sh`:** doctor checks config migration state (env key renames, scope drift, CLAUDE.md sync, placeholder values). healthcheck checks runtime health. They complement each other.

**4 day-1 checks:**
- `embed-model` — `JCODEMUNCH_EMBED_MODEL` present in `.env`
- `jcodemunch-scope` — jcodemunch not registered at stale `local`/`project` scope
- `claude-md-sync` — `~/.claude/CLAUDE.md` in sync with repo copy
- `env-placeholders` — no unfilled template values in `.env`

**`--fix` is safe:** uses atomic writes (`.env.tmp` → `mv`) with `.env.bak` backup before any mutation.

## How to test

\`\`\`bash
bash scripts/refinery-doctor.sh           # dry-run, all OK
bash scripts/refinery-doctor.sh --fix     # no-op on clean machine
bash scripts/refinery-doctor.sh --check embed-model
\`\`\`

## Checklist
- [x] `--fix` uses atomic writes with `.env.bak` backup
- [x] All checks are safe to run dry (no side effects without `--fix`)
- [x] `--check <name>` runs a single check
- [x] Exit 0 = clean, exit 1 = pending migrations
EOF
)"
```

---

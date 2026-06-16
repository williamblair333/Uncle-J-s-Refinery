#!/usr/bin/env bash
# healthcheck.sh — runtime invariants check for Uncle J's Refinery.
#
# Complements verify.sh (install-time binary checks) by verifying
# everything is actually wired up and responding. Catches the silent
# regressions that install-time checks miss:
#   - jcodemunch registered at local scope (masks the venv path)
#   - langfuse wiped from .venv by a uv sync (Stop hook dies silently)
#   - docker stack crashed overnight
#   - MCP_TIMEOUT or Langfuse env reset
#   - secrets committed to the working tree
#
# Usage:
#   ./healthcheck.sh            # --quick (default; <5s; safe for SessionStart)
#   ./healthcheck.sh --quick
#   ./healthcheck.sh --full     # adds end-to-end smoke test (~30s; nested claude -p)
#
# Exit: 0 if all checks pass, 1 if any check fails.
# Final stdout line is machine-parseable:
#   HEALTHCHECK: ok
#   HEALTHCHECK: fail (<count>) -- <first failing check>

set -uo pipefail
# Deliberately NOT using -e: a failed check must not abort the rest.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="quick"
FIX_ALL=false
for arg in "$@"; do
    case "$arg" in
        --quick)  MODE="quick" ;;
        --full)   MODE="full"  ;;
        --fixall) FIX_ALL=true ;;
        -h|--help)
            sed -n '1,18p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

step() { printf '\n==> %s\n' "$*" >&2; }
ok()   { printf '    OK  %s\n' "$*" >&2; }
warn() { printf '    W   %s\n' "$*" >&2; }
bad()  { printf '    X   %s\n' "$*" >&2; }
hint() {
    printf '        fix: %s\n' "$*" >&2
    # When hint is a runnable command: auto-run under --fixall, or offer [y/N] interactively.
    if [[ "$*" == run:\ * ]]; then
        local cmd="${*#run: }"
        cmd="${cmd%  (*}"   # strip trailing parenthetical notes like "  (or re-run X)"
        if [[ "${FIX_ALL:-false}" == true ]]; then
            printf '        Auto-fixing: %s\n' "$cmd" >&2
            bash -c "$cmd" || printf '        Command exited non-zero — check output above\n' >&2
        elif [[ -t 2 ]]; then
            printf '        Fix it now? [y/N] ' >&2
            local reply=""
            read -r reply </dev/tty 2>/dev/null || true
            if [[ "$reply" =~ ^[Yy]$ ]]; then
                printf '        Running: %s\n' "$cmd" >&2
                bash -c "$cmd" || printf '        Command exited non-zero — check output above\n' >&2
            fi
        fi
    fi
}

checks_failed=0
first_fail=""
record_fail() {
    checks_failed=$((checks_failed + 1))
    [ -z "$first_fail" ] && first_fail="$1"
}

# ----- 1. verify.sh passes --------------------------------------------------
check_verify() {
    step "verify.sh — install-time binaries"
    if "$REPO_ROOT/verify.sh" >/dev/null 2>&1; then
        ok "verify.sh all PASS"
    else
        bad "verify.sh reported failures"
        hint "run: $REPO_ROOT/verify.sh   # then re-run whichever install step failed"
        record_fail "verify.sh"
    fi
}

# ----- 2. all 6 stack MCP servers connected ---------------------------------
check_mcp_connected() {
    step "MCP servers — 6 stack servers connected"
    local output
    output="$(claude mcp list 2>&1)" || {
        bad "claude mcp list failed"
        hint "run: claude --version   # then: $REPO_ROOT/install.sh --auto-register"
        record_fail "mcp-list"
        return
    }
    local missing=()
    for name in duckdb jcodemunch jdatamunch jdocmunch serena context7; do
        if ! printf '%s\n' "$output" | grep -qE "^${name}: .*[✓✔] Connected"; then
            missing+=("$name")
        fi
    done
    # duckdb launches via uvx (mcp-server-motherduck); its first MCP handshake at
    # session-open can outrun a single probe on a cold machine. It cold-starts in
    # <1s once the uvx cache is warm, so poll up to ~15s before declaring failure:
    # a genuine down state still surfaces, only the cold-start race is absorbed.
    if [[ ${#missing[@]} -eq 1 && "${missing[0]}" == "duckdb" ]]; then
        local i
        for i in 1 2 3 4 5; do
            sleep 3
            output="$(claude mcp list 2>&1)"
            if printf '%s\n' "$output" | grep -qE "^duckdb: .*[✓✔] Connected"; then
                ok "all 6 stack servers Connected (duckdb warmed after ${i} retr$([ "$i" -eq 1 ] && echo y || echo ies))"
                return
            fi
        done
        bad "duckdb not Connected after 5 retries (~15s)"
        hint "run: uvx mcp-server-motherduck --help   # warm the uvx cache, then: $REPO_ROOT/install.sh --auto-register"
        record_fail "mcp-servers-down(duckdb)"
        return
    fi
    if [ ${#missing[@]} -eq 0 ]; then
        ok "all 6 stack servers Connected"
    elif [ ${#missing[@]} -ge 5 ]; then
        # All (or nearly all) servers down = Claude Code not running or not restarted.
        # Re-registering with --auto-register cannot fix a missing session.
        bad "not Connected: ${missing[*]}"
        hint "restart Claude Code — MCP servers only show Connected inside an active session; --auto-register will not help"
        record_fail "mcp-servers-down(${missing[0]})"
    else
        bad "not Connected: ${missing[*]}"
        hint "run: $REPO_ROOT/install.sh --auto-register"
        record_fail "mcp-servers-down(${missing[0]})"
    fi
}

# ----- 3. jcodemunch at venv path (NOT uvx) --------------------------------
check_jcodemunch_path() {
    step "jcodemunch — stack venv binary (not uvx)"
    local output
    local project_venv="$REPO_ROOT/.venv/bin/jcodemunch-mcp"
    output="$(claude mcp get jcodemunch 2>&1)" || {
        bad "claude mcp get jcodemunch failed"
        record_fail "jcodemunch-get"
        return
    }
    if printf '%s\n' "$output" | grep -qF "$project_venv"; then
        ok "jcodemunch -> $project_venv"
    elif printf '%s\n' "$output" | grep -qE "$HOME/.code-index/local-.+/jcodemunch-mcp"; then
        local actual_path
        actual_path=$(printf '%s\n' "$output" | grep -oE "[^ ]+jcodemunch-mcp" | head -1)
        ok "jcodemunch -> $actual_path (code-index venv — updated by reindex)"
    else
        bad "jcodemunch not at a known venv path — may be uvx or stale local-scope registration"
        hint "run: claude mcp remove jcodemunch -s local ; claude mcp remove jcodemunch -s project"
        record_fail "jcodemunch-wrong-scope"
    fi
}

# ----- 3b. venv SQLite is the WAL-race-fixed 3.51.3 (vendored pysqlite3) ----
# A bare `uv sync` used to silently revert pysqlite3 to the PyPI 3.51.1 wheel
# (WAL data-race bug). pyproject pins a vendored 3.51.3 wheel; this asserts the
# pin held, so a future Python-bump fallback to PyPI fails LOUD instead of silent.
check_sqlite_version() {
    step "venv SQLite — 3.51.3 (vendored pysqlite3, WAL-race fix)"
    local want="3.51.3" got
    got="$("$REPO_ROOT/.venv/bin/python" -c 'import sqlite3; print(sqlite3.sqlite_version)' 2>/dev/null)" || {
        bad "could not query venv sqlite3 version"
        hint "run: $REPO_ROOT/install.sh   # rebuilds the venv + pysqlite3 patch"
        record_fail "sqlite-version-unknown"
        return
    }
    if [ "$got" = "$want" ]; then
        ok "venv sqlite3 = $got (vendored wheel)"
    else
        bad "venv sqlite3 = $got, expected $want — pin reverted (likely PyPI 3.51.1 WAL bug)"
        hint "run: bash $REPO_ROOT/scripts/build-vendored-pysqlite3.sh   # rebuild wheel for this Python, then uv lock && uv sync"
        record_fail "sqlite-version($got)"
    fi
}

# ----- 4. MCP_TIMEOUT = 60000 ----------------------------------------------
check_mcp_timeout() {
    step "settings.json — MCP_TIMEOUT=60000"
    local actual
    actual="$(python3 -c 'import json,os; print(json.load(open(os.path.expanduser("~/.claude/settings.json")))["env"].get("MCP_TIMEOUT","<unset>"))' 2>/dev/null)"
    if [ "$actual" = "60000" ]; then
        ok "MCP_TIMEOUT=60000"
    else
        bad "MCP_TIMEOUT=$actual (expected 60000)"
        hint "re-run: $REPO_ROOT/install.sh    # step 5b rewrites the setting"
        record_fail "mcp-timeout"
    fi
}

# Helper: returns non-empty if Langfuse is configured (LANGFUSE_PUBLIC_KEY in settings.json).
# Gates all three Langfuse checks — skip silently when Langfuse was never installed.
_langfuse_configured() {
    python3 -c \
        'import json,os,sys; d=json.load(open(os.path.expanduser("~/.claude/settings.json"))); sys.stdout.write(d.get("env",{}).get("LANGFUSE_PUBLIC_KEY",""))' \
        2>/dev/null || true
}

# ----- 5. Langfuse compose health ------------------------------------------
check_langfuse_compose() {
    step "Langfuse compose — 6 up, 4 healthy"
    if [[ -z "$(_langfuse_configured)" ]]; then
        ok "Langfuse not configured (LANGFUSE_PUBLIC_KEY absent) — skipping; run install-langfuse.sh to enable"
        return
    fi
    local compose="$REPO_ROOT/claude-code-langfuse-template/docker-compose.yml"
    if [ ! -f "$compose" ]; then
        bad "compose file missing: $compose"
        hint "run: $REPO_ROOT/install-langfuse.sh"
        record_fail "langfuse-compose-missing"
        return
    fi
    local json
    json="$(docker compose -f "$compose" ps --format json 2>&1)" || {
        bad "docker compose ps failed"
        hint "check: docker info    # is the docker daemon running?"
        record_fail "docker-down"
        return
    }
    # --format json in compose v2 prints one JSON object per line (ndjson) on Linux.
    local total running healthy
    total="$(printf '%s\n' "$json" | awk 'NF' | wc -l)"
    running="$(printf '%s\n' "$json" | awk 'NF' | python3 -c 'import sys,json; print(sum(1 for L in sys.stdin if json.loads(L).get("State")=="running"))')"
    healthy="$(printf '%s\n' "$json" | awk 'NF' | python3 -c 'import sys,json; print(sum(1 for L in sys.stdin if json.loads(L).get("Health")=="healthy"))')"
    if [ "$total" -ge 6 ] && [ "$running" -ge 6 ] && [ "$healthy" -ge 4 ]; then
        ok "$running running, $healthy healthy"
    else
        bad "compose state: total=$total running=$running healthy=$healthy (want >=6 running, >=4 healthy)"
        hint "run: docker compose -f $compose up -d"
        record_fail "langfuse-unhealthy"
    fi
}

# ----- 6. Langfuse /api/public/health --------------------------------------
check_langfuse_api() {
    step "Langfuse API — /api/public/health"
    if [[ -z "$(_langfuse_configured)" ]]; then
        ok "Langfuse not configured — skipping"
        return
    fi
    local body
    body="$(curl -s --max-time 3 http://localhost:3050/api/public/health 2>&1)"
    if printf '%s' "$body" | grep -q '"status":"OK"'; then
        ok "status=OK"
    else
        bad "health endpoint did not return status=OK — got: $(printf '%s' "$body" | head -c 80)"
        hint "run: docker compose -f $REPO_ROOT/claude-code-langfuse-template/docker-compose.yml logs --tail=50 langfuse-web"
        record_fail "langfuse-api"
    fi
}

# ----- 7. langfuse SDK importable from stack venv --------------------------
check_langfuse_sdk() {
    step "Langfuse SDK — importable from stack venv"
    if [[ -z "$(_langfuse_configured)" ]]; then
        ok "Langfuse not configured — skipping"
        return
    fi
    local py="$REPO_ROOT/.venv/bin/python"
    if [ ! -x "$py" ]; then
        bad "stack venv python missing at $py"
        hint "run: $REPO_ROOT/install.sh"
        record_fail "venv-python-missing"
        return
    fi
    if "$py" -c "from langfuse import Langfuse" >/dev/null 2>&1; then
        ok "from langfuse import Langfuse -> OK"
    else
        bad "langfuse not importable from $py — Stop hook silently dies without this"
        hint "run: uv pip install --python $py --upgrade 'langfuse>=3.0,<4'   (or re-run install-langfuse.sh)"
        record_fail "langfuse-sdk-missing"
    fi
}

# ----- 8. skills installed --------------------------------------------------
_REQUIRED_SKILLS=(dream-synthesizer outcomes orchestrator per-task-review-cycle post-upgrade-mcp-integration)

check_skills() {
    step "skills — dreaming, outcomes, orchestrator installed"
    local missing=0
    for skill in "${_REQUIRED_SKILLS[@]}"; do
        if [ -f "$HOME/.claude/skills/$skill/SKILL.md" ]; then
            ok "skill: $skill"
        else
            bad "skill missing: $skill"
            hint "run: bash $REPO_ROOT/install-reliability.sh  (or for dream-synthesizer: bash $REPO_ROOT/features/dreaming/install.sh)"
            record_fail "skill-$skill"
            missing=$((missing+1))
        fi
    done
    if [ -f "$HOME/.claude/commands/dream.md" ]; then
        ok "/dream slash command installed"
    else
        bad "/dream command missing"
        hint "run: bash $REPO_ROOT/features/dreaming/install.sh"
        record_fail "dream-command"
    fi
    if [ -f "$HOME/.claude/commands/stats.md" ]; then
        ok "/stats slash command installed"
    else
        bad "/stats command missing"
        hint "run: bash $REPO_ROOT/features/session-stats/install.sh"
        record_fail "stats-command"
    fi
    if bash "$REPO_ROOT/features/session-stats/stats.sh" --dry-run >/dev/null 2>&1; then
        ok "stats.sh --dry-run exits 0"
    else
        bad "stats.sh --dry-run failed"
        hint "check: bash $REPO_ROOT/features/session-stats/stats.sh --dry-run"
        record_fail "stats-dry-run"
    fi
    if crontab -l 2>/dev/null | grep -q 'uncle-j-session-stats'; then
        ok "session-stats cron registered"
    else
        bad "session-stats cron not registered"
        hint "run: bash $REPO_ROOT/features/session-stats/install.sh"
        record_fail "stats-cron"
    fi
}

# ----- 9a. agentskills.io compliance: name matches folder, description present -----
check_skill_compliance() {
    step "skills — agentskills.io compliance (name matches folder, description present)"
    local skills_dir="$REPO_ROOT/global-skills"
    local failed=0

    for skill_dir in "$skills_dir"/*/; do
        [[ -d "$skill_dir" ]] || continue
        local folder_name
        folder_name="$(basename "$skill_dir")"
        local skill_md="$skill_dir/SKILL.md"

        if [[ ! -f "$skill_md" ]]; then
            bad "skill: $folder_name — missing SKILL.md"
            hint "inspect: ls $skill_dir"
            record_fail "skill-compliance-missing-$folder_name"
            failed=$((failed + 1))
            continue
        fi

        local name_field
        name_field="$(grep -m1 '^name:' "$skill_md" | sed 's/^name:[[:space:]]*//' | tr -d '\r')"
        if [[ "$name_field" != "$folder_name" ]]; then
            bad "skill: $folder_name — name: '$name_field' does not match folder"
            hint "edit $skill_md: set name: $folder_name"
            record_fail "skill-compliance-name-$folder_name"
            failed=$((failed + 1))
        fi

        local desc_field
        desc_field="$(grep -m1 '^description:' "$skill_md" | sed 's/^description:[[:space:]]*//' | tr -d '\r')"
        if [[ -z "$desc_field" ]]; then
            bad "skill: $folder_name — missing description field"
            hint "edit $skill_md: add description: <one-line summary>"
            record_fail "skill-compliance-desc-$folder_name"
            failed=$((failed + 1))
        fi
    done

    local skill_count
    skill_count="$(ls -d "$skills_dir"/*/ 2>/dev/null | wc -l | tr -d ' ')"
    [[ $failed -eq 0 ]] && ok "all $skill_count global skills agentskills.io compliant"
}

# ----- agents installed -----
check_agents() {
    step "agents — core agents installed"
    local missing=0
    for agent in planner code-reviewer security-reviewer architect tdd-guide silent-failure-hunter; do
        if [ -f "$HOME/.claude/agents/${agent}.md" ]; then
            ok "agent: $agent"
        else
            bad "agent missing: $agent"
            hint "run: bash $REPO_ROOT/install-reliability.sh"
            record_fail "agent-$agent"
            missing=$((missing+1))
        fi
    done
}


# ----- 9d. crons: all expected jobs registered -----------------------------
check_crons() {
    step "crontab — Uncle J jobs registered"
    local tab
    tab="$(crontab -l 2>/dev/null || true)"
    local missing=()
    declare -A EXPECTED=(
        [uncle-j-session-stats]="features/session-stats/stats.sh"
        [uncle-j-dreaming]="features/dreaming/dream.sh"
        [uncle-j-auto-maintain]="bash $REPO_ROOT/scripts/auto-maintain.sh"
        [uncle-j-healthcheck-notify]="bash $REPO_ROOT/scripts/healthcheck-notify.sh"
        [uncle-j-jcodemunch-reindex]="bash $REPO_ROOT/scripts/jcodemunch-reindex.sh"
        [uncle-j-memweave-sync]="scripts/memweave/sync_memory.sh"
    )
    for label in "${!EXPECTED[@]}"; do
        if printf '%s\n' "$tab" | grep -q "$label"; then
            ok "cron: $label"
        else
            missing+=("$label")
        fi
    done
    if [ ${#missing[@]} -gt 0 ]; then
        for m in "${missing[@]}"; do
            bad "cron missing: $m"
        done
        hint "run: bash $REPO_ROOT/install.sh   (re-registers crons)"
        record_fail "cron-missing(${missing[0]})"
    fi
}

# ----- 9e. stack freshness: all git packages at HEAD -----------------------
check_stack_freshness() {
    step "stack freshness — packages at HEAD"
    local freshness_exit=0
    bash "$REPO_ROOT/scripts/check-stack-freshness.sh" >/dev/null 2>&1 || freshness_exit=$?
    if [ "$freshness_exit" -eq 0 ]; then
        ok "all packages at HEAD"
    else
        warn "one or more packages behind HEAD — run check-stack-freshness.sh for details"
        hint "run: cd $REPO_ROOT && uv lock --upgrade-package jcodemunch-mcp --upgrade-package jdatamunch-mcp --upgrade-package jdocmunch-mcp && uv sync --inexact"
    fi
}

# ----- 9f. git post-merge hook wired ---------------------------------------
check_post_merge_hook() {
    step "git — post-merge hook wired"
    local hook="$REPO_ROOT/.git/hooks/post-merge"
    local expected_target="$REPO_ROOT/scripts/post-merge-hook.sh"
    if [ -L "$hook" ] && [ "$(readlink "$hook")" = "$expected_target" ]; then
        ok "post-merge hook -> $expected_target"
    elif [ -x "$hook" ]; then
        bad "post-merge hook exists but is not the expected symlink"
        hint "run: ln -sfn $expected_target $hook"
        record_fail "post-merge-hook-wrong"
    else
        bad "post-merge hook not installed"
        hint "run: ln -sfn $expected_target $hook"
        record_fail "post-merge-hook-missing"
    fi
}

# ----- MEMORY.md: stale-entry advisory scan --------------------------------
check_memory_staleness() {
    step "MEMORY.md: stale-entry advisory scan"
    local mem_path
    mem_path="$HOME/.claude/projects/$(printf '%s' "$REPO_ROOT" | tr '/' '-')/memory/MEMORY.md"
    if [ ! -f "$mem_path" ]; then
        ok "MEMORY.md not found — skipping"
        return
    fi
    local stale_lines
    stale_lines="$(grep -iE "\b(pending|awaiting|needs [a-z]|consider filing|not yet|TODO|FIXME)\b" "$mem_path" 2>/dev/null || true)"
    if [ -z "$stale_lines" ]; then
        ok "no stale-keyword matches in MEMORY.md"
    else
        warn "MEMORY.md contains entries worth verifying before treating as current fact:"
        while IFS= read -r line; do
            printf '  → %s\n' "$line"
        done <<< "$stale_lines"
        hint "cross-check flagged entries against git log / source before reporting"
    fi
}

# ----- 9h. jdocmunch index not empty ----------------------------------------
check_docmunch_indexed() {
    step "jdocmunch — index populated"
    local idx="$HOME/.doc-index"
    if [ ! -d "$idx" ] || [ -z "$(ls -A "$idx" 2>/dev/null)" ]; then
        bad "jdocmunch index is empty — docs not searchable via jdocmunch"
        hint "run: $REPO_ROOT/.venv/bin/jdocmunch-mcp index-local --path $REPO_ROOT"
        record_fail "jdocmunch-empty-index"
    else
        local count
        count=$(ls "$idx" | wc -l)
        ok "jdocmunch index: ${count} repo(s) in $idx"
    fi
}

# ----- working tree: no leaked Langfuse credentials -----------------------
# Scoped intentionally to Langfuse keys (sk-lf-*) only.
# For broader secret scanning use gitleaks or trufflehog.
check_secrets() {
    step "working tree: Langfuse credentials scan"
    local pattern='sk-lf-[a-f0-9]{16,}'
    local hits
    hits="$(cd "$REPO_ROOT" && git grep -E "$pattern" 2>/dev/null || true)"
    if [ -z "$hits" ]; then
        ok "no sk-lf-* Langfuse keys in tracked files"
    else
        bad "Langfuse secret key found in tracked files"
        printf '%s\n' "$hits" | head -3 >&2
        hint "add the file to .gitignore or rotate the key and redact"
        record_fail "secrets"
    fi
}

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

# ----- 9l. embedding model downloaded + canary pinned ----------------------
check_embedding_canary() {
    step "jcodemunch — embedding model + canary"
    local model_dir="$HOME/.code-index/models/all-MiniLM-L6-v2"
    local canary="$HOME/.code-index/embed_canary.json"
    local env_file="$REPO_ROOT/.env"

    # Check model files
    if [[ ! -f "$model_dir/model.onnx" ]]; then
        bad "ONNX embedding model not downloaded"
        hint "run: $REPO_ROOT/.venv/bin/jcodemunch-mcp download-model"
        record_fail "embedding-model-missing"
        return
    fi
    ok "embedding model present ($model_dir)"

    # Check env var set
    if ! grep -q "^JCODEMUNCH_EMBED_MODEL=" "$env_file" 2>/dev/null; then
        bad "JCODEMUNCH_EMBED_MODEL not set in .env"
        hint "add: JCODEMUNCH_EMBED_MODEL=all-MiniLM-L6-v2 to $env_file"
        record_fail "embedding-env-not-set"
        return
    fi
    ok "JCODEMUNCH_EMBED_MODEL set in .env"

    # Check canary pinned
    if [[ ! -f "$canary" ]]; then
        bad "embedding canary not pinned — semantic drift detection inactive"
        hint "run: bash $REPO_ROOT/scripts/pin-canary.sh"
        record_fail "embedding-canary-not-pinned"
        return
    fi
    ok "embedding canary pinned ($(wc -c < "$canary" | tr -d ' ') bytes)"
}

# ----- 9k. auto-maintain crons registered ----------------------------------
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

# ===== full-mode extras =====================================================
# ----- 9. Stop hook wiring: direct invocation writes a log line ------------
check_smoke_hook() {
    step "smoke — stop hook writes to langfuse_hook.log"
    local log="$HOME/.claude/state/langfuse_hook.log"
    local hook="$HOME/.claude/hooks/langfuse_hook.py"
    local py="$REPO_ROOT/.venv/bin/python"
    local settings="$HOME/.claude/settings.json"
    local before after delta
    # We invoke the hook directly rather than via `claude -p`: the CLI's
    # print mode does not fire Stop hooks, so a nested session produces no
    # log line regardless of wait time. Direct invocation exercises the same
    # wiring the harness uses: venv python, hook script, env from settings,
    # Langfuse SDK, log write.
    before="$(wc -l < "$log" 2>/dev/null || echo 0)"
    env \
        LANGFUSE_PUBLIC_KEY="$(python3 -c 'import json,os; print(json.load(open(os.path.expanduser("~/.claude/settings.json")))["env"].get("LANGFUSE_PUBLIC_KEY",""))' 2>/dev/null)" \
        LANGFUSE_SECRET_KEY="$(python3 -c 'import json,os; print(json.load(open(os.path.expanduser("~/.claude/settings.json")))["env"].get("LANGFUSE_SECRET_KEY",""))' 2>/dev/null)" \
        LANGFUSE_HOST="$(python3 -c 'import json,os; print(json.load(open(os.path.expanduser("~/.claude/settings.json")))["env"].get("LANGFUSE_HOST",""))' 2>/dev/null)" \
        TRACE_TO_LANGFUSE=true \
        "$py" "$hook" </dev/null >/dev/null 2>&1 || true
    after="$(wc -l < "$log" 2>/dev/null || echo 0)"
    delta=$((after - before))
    if [ "$delta" -ge 1 ]; then
        ok "log delta = $delta (hook fired)"
    else
        bad "log delta = 0 — hook did not fire"
        hint "check: tail -5 $log ; and: $py -c 'from langfuse import Langfuse' ; and: test -r $hook ; and: grep LANGFUSE_ $settings"
        record_fail "hook-no-fire"
    fi
}

# ----- 10. Langfuse trace API has a recent trace ---------------------------
check_trace_api() {
    step "Langfuse traces API — recent trace exists"
    local pk sk host
    pk="$(python3 -c 'import json,os; print(json.load(open(os.path.expanduser("~/.claude/settings.json")))["env"].get("LANGFUSE_PUBLIC_KEY",""))' 2>/dev/null)"
    sk="$(python3 -c 'import json,os; print(json.load(open(os.path.expanduser("~/.claude/settings.json")))["env"].get("LANGFUSE_SECRET_KEY",""))' 2>/dev/null)"
    host="$(python3 -c 'import json,os; print(json.load(open(os.path.expanduser("~/.claude/settings.json")))["env"].get("LANGFUSE_HOST",""))' 2>/dev/null)"
    if [ -z "$pk" ] || [ -z "$sk" ] || [ -z "$host" ]; then
        bad "Langfuse creds missing from ~/.claude/settings.json env block"
        record_fail "langfuse-creds"
        return
    fi
    local resp
    resp="$(curl -s --max-time 5 -u "$pk:$sk" "${host%/}/api/public/traces?limit=1" 2>&1)"
    if printf '%s' "$resp" | grep -qE '"timestamp"'; then
        ok "trace API returned a trace"
    else
        bad "trace API returned no trace (got: $(printf '%s' "$resp" | head -c 80))"
        record_fail "trace-api"
    fi
}

# ----- 9m. jcodemunch-watch inotify daemon active --------------------------
check_jcodemunch_watch() {
    step "jcodemunch-watch — inotify reindex daemon active"
    # Only the literal "active" is OK. "inactive"/"failed" = a silently-died daemon
    # (out-of-band edits stop auto-reindexing). Anything else (empty output, a
    # "Failed to connect to bus" error under a cron context with no user DBUS) is
    # NOT a failure — warn and skip, so cron healthchecks don't spam false fails.
    local state
    state="$(systemctl --user is-active jcodemunch-watch 2>/dev/null || true)"
    case "$state" in
        active)
            ok "jcodemunch-watch.service active"
            ;;
        inactive|failed)
            bad "jcodemunch-watch.service is $state — out-of-band edits won't auto-reindex"
            hint "run: systemctl --user enable --now jcodemunch-watch"
            record_fail "jcodemunch-watch-$state"
            ;;
        *)
            warn "jcodemunch-watch state indeterminate ('${state:-no user systemd bus}') — skipping (cron context?)"
            ;;
    esac
}

# ----- 9n. memweave memory index fresh -------------------------------------
check_memweave_fresh() {
    step "memweave — memory index fresh (<48h)"
    local idx="$HOME/.uncle-j-memory/.memweave/index.sqlite"
    if [[ ! -f "$idx" ]]; then
        bad "memweave index missing ($idx) — prior-art search is blind"
        hint "run: bash $REPO_ROOT/scripts/memweave/sync_memory.sh --all"
        record_fail "memweave-index-missing"
        return
    fi
    local mtime now age_h
    mtime="$(stat -c %Y "$idx" 2>/dev/null || echo 0)"
    now="$(date +%s)"
    age_h=$(( (now - mtime) / 3600 ))
    if (( age_h <= 48 )); then
        ok "memweave index fresh (${age_h}h old)"
    else
        bad "memweave index stale (${age_h}h old, >48h) — nightly sync may have stopped"
        hint "run: bash $REPO_ROOT/scripts/memweave/sync_memory.sh --all"
        record_fail "memweave-index-stale"
    fi
}

# ----- 9o. dreaming last-run freshness (>36h = cron failing) ---------------
check_dreaming_runtime() {
    step "dreaming — runtime health (last-run freshness)"
    local last_run="$REPO_ROOT/state/dreaming-last-run.txt"
    local log="$REPO_ROOT/state/dreaming.log"

    if [[ ! -f "$last_run" ]]; then
        warn "dreaming-last-run.txt missing — dreaming has never completed (normal on fresh install)"
        return
    fi

    local mtime now age_h
    mtime="$(stat -c %Y "$last_run" 2>/dev/null || echo 0)"
    now="$(date +%s)"
    age_h=$(( (now - mtime) / 3600 ))

    if (( age_h <= 36 )); then
        ok "dreaming last completed ${age_h}h ago"
    else
        bad "dreaming last-run is ${age_h}h stale (>36h) — cron likely failing"
        if [[ -f "$log" ]]; then
            local clues
            clues="$(tail -30 "$log" | grep '!!' || true)"
            if [[ -n "$clues" ]]; then
                printf '%s\n' "$clues" | head -3 | while IFS= read -r line; do
                    printf '        %s\n' "$line" >&2
                done
            fi
        fi
        hint "check: tail -30 $log ; fix: bash $REPO_ROOT/features/dreaming/dream.sh --dry-run"
        record_fail "dreaming-stale(${age_h}h)"
    fi
}

# ----- 9p. auto-maintain: no shell errors in recent log --------------------
check_auto_maintain_runtime() {
    step "auto-maintain — no shell errors in recent log"
    local log="$REPO_ROOT/state/auto-maintain.log"
    if [[ ! -f "$log" ]]; then
        warn "auto-maintain.log missing — auto-maintain has never run"
        return
    fi
    local recent_errors
    recent_errors="$(tail -50 "$log" | grep -E ': line [0-9]+:|bad substitution|syntax error' || true)"
    if [[ -n "$recent_errors" ]]; then
        bad "auto-maintain.log has recent shell error(s):"
        printf '%s\n' "$recent_errors" | head -5 | while IFS= read -r line; do
            printf '        %s\n' "$line" >&2
        done
        hint "check: tail -50 $log"
        record_fail "auto-maintain-errors"
    else
        ok "auto-maintain.log: no recent shell errors"
    fi
}

# ===== main =================================================================
# verify.sh is install-time (uvx cache warmup takes ~5s); run it only in
# --full mode. --quick sticks to runtime invariants for a ~6s session-start
# banner.
step "healthcheck mode=$MODE  repo=$REPO_ROOT"
check_mcp_connected
check_jcodemunch_path
check_sqlite_version
check_mcp_timeout
check_langfuse_compose
check_langfuse_api
check_langfuse_sdk
check_skills
check_skill_compliance
check_agents
check_crons
check_stack_freshness
check_post_merge_hook
check_memory_staleness
check_docmunch_indexed
check_secrets
check_jcodemunch_index_fresh
check_untracked_skills
check_auto_maintain_cron
check_embedding_canary
check_jcodemunch_watch
check_memweave_fresh
check_dreaming_runtime
check_auto_maintain_runtime
if [ "$MODE" = "full" ]; then
    check_verify
    check_smoke_hook
    check_trace_api
fi

if [ "$checks_failed" -eq 0 ]; then
    printf '\nHEALTHCHECK: ok\n'
    exit 0
else
    printf '\nHEALTHCHECK: fail (%d) -- %s\n' "$checks_failed" "$first_fail"
    exit 1
fi

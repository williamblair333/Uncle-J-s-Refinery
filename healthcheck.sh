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
for arg in "$@"; do
    case "$arg" in
        --quick) MODE="quick" ;;
        --full)  MODE="full"  ;;
        -h|--help)
            sed -n '1,18p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

step() { printf '\n==> %s\n' "$*" >&2; }
ok()   { printf '    OK  %s\n' "$*" >&2; }
bad()  { printf '    X   %s\n' "$*" >&2; }
hint() { printf '        fix: %s\n' "$*" >&2; }

checks_failed=0
first_fail=""
record_fail() {
    checks_failed=$((checks_failed + 1))
    [ -z "$first_fail" ] && first_fail="$1"
}

# ----- 1. verify.sh passes --------------------------------------------------
check_verify() {
    step "1. verify.sh (install-time binaries)"
    if "$REPO_ROOT/verify.sh" >/dev/null 2>&1; then
        ok "verify.sh all PASS"
    else
        bad "verify.sh reported failures"
        hint "run: $REPO_ROOT/verify.sh   # then re-run whichever install step failed"
        record_fail "verify.sh"
    fi
}

# ----- 2. all 7 stack MCP servers connected ---------------------------------
check_mcp_connected() {
    step "2. claude mcp list — 7 stack servers ✓ Connected"
    local output
    output="$(claude mcp list 2>&1)" || {
        bad "claude mcp list failed"
        hint "run: claude --version   # then: $REPO_ROOT/install.sh --auto-register"
        record_fail "mcp-list"
        return
    }
    local missing=()
    for name in duckdb jcodemunch jdatamunch jdocmunch mempalace serena context7; do
        if ! printf '%s\n' "$output" | grep -qE "^${name}: .*✓ Connected"; then
            missing+=("$name")
        fi
    done
    if [ ${#missing[@]} -eq 0 ]; then
        ok "all 7 stack servers Connected"
    else
        bad "not Connected: ${missing[*]}"
        hint "run: $REPO_ROOT/install.sh --auto-register"
        record_fail "mcp-servers-down(${missing[0]})"
    fi
}

# ----- 3. jcodemunch at venv path (NOT uvx) --------------------------------
check_jcodemunch_path() {
    step "3. jcodemunch running from stack venv (not uvx)"
    local output expected="$REPO_ROOT/.venv/bin/jcodemunch-mcp"
    output="$(claude mcp get jcodemunch 2>&1)" || {
        bad "claude mcp get jcodemunch failed"
        record_fail "jcodemunch-get"
        return
    }
    if printf '%s\n' "$output" | grep -qF "$expected"; then
        ok "jcodemunch -> $expected"
    else
        bad "jcodemunch not at venv path — likely a stale local-scope registration"
        hint "run: claude mcp remove jcodemunch -s local ; claude mcp remove jcodemunch -s project"
        record_fail "jcodemunch-wrong-scope"
    fi
}

# ----- 4. MCP_TIMEOUT = 60000 ----------------------------------------------
check_mcp_timeout() {
    step "4. MCP_TIMEOUT=60000 in ~/.claude/settings.json"
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

# ----- 5. Langfuse compose health ------------------------------------------
check_langfuse_compose() {
    step "5. Langfuse docker compose: 6 up, 4 healthy"
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
    step "6. Langfuse API /api/public/health"
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
    step "7. langfuse SDK importable from stack venv"
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

# ----- 8. no leaked secrets in tree ----------------------------------------
check_secrets() {
    step "8. working tree: no leaked secrets"
    local pattern='sk-lf-[a-f0-9]{16,}|PASSWORD=[a-zA-Z0-9]{8,}'
    local hits
    hits="$(cd "$REPO_ROOT" && git grep -iE "$pattern" 2>/dev/null || true)"
    if [ -z "$hits" ]; then
        ok "no sk-lf-* or PASSWORD=... matches"
    else
        bad "secret-looking strings found in tracked files"
        printf '%s\n' "$hits" | head -3 >&2
        hint "review the matches; add the file to .gitignore or redact"
        record_fail "secrets"
    fi
}

# ===== full-mode extras =====================================================
# ----- 9. Stop hook wiring: direct invocation writes a log line ------------
check_smoke_hook() {
    step "9. smoke: Stop hook writes a new line to langfuse_hook.log"
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
    step "10. Langfuse traces API: recent trace exists"
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

# ===== main =================================================================
# verify.sh is install-time (uvx cache warmup takes ~5s); run it only in
# --full mode. --quick sticks to runtime invariants for a ~6s session-start
# banner.
step "healthcheck mode=$MODE  repo=$REPO_ROOT"
check_mcp_connected
check_jcodemunch_path
check_mcp_timeout
check_langfuse_compose
check_langfuse_api
check_langfuse_sdk
check_secrets
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

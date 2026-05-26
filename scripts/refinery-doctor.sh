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

# Atomic .env write: backup → write to tmp → rename
# Usage: atomic_env_write <new_content_string>
atomic_env_write() {
    local new_content="$1"
    cp "$ENV_FILE" "${ENV_FILE}.bak"
    printf '%s' "$new_content" > "${ENV_FILE}.tmp"
    mv "${ENV_FILE}.tmp" "$ENV_FILE"
}

# ── checks ───────────────────────────────────────────────────────────────────

run_check() {
    local name="$1"
    [[ -n "$ONLY_CHECK" && "$ONLY_CHECK" != "$name" ]] && return
    "check_${name//-/_}"
}

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
        [[ "${current: -1}" != $'\n' ]] && current+=$'\n'
        current+="JCODEMUNCH_EMBED_MODEL=all-MiniLM-L6-v2"$'\n'
        atomic_env_write "$current"
        fixed "appended JCODEMUNCH_EMBED_MODEL=all-MiniLM-L6-v2 to .env (backup: .env.bak)"
    fi
}

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

check_env_placeholders() {
    step "env-placeholders — template values in .env"
    if [[ ! -f "$ENV_FILE" ]]; then
        info ".env not found — skipping"
        return
    fi
    local placeholder_patterns=('your-' 'changeme' 'PLACEHOLDER' 'TODO' 'xxx' 'example\.com' '<your')
    local found_lines=()
    for pattern in "${placeholder_patterns[@]}"; do
        while IFS= read -r line; do
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
        local key="${line%%=*}"
        suggest "review: $key  (value looks like a placeholder)"
    done
    record_migration "env-placeholders"
    info "this check is report-only — fill in real values manually"
}

# ── run ──────────────────────────────────────────────────────────────────────

run_check embed-model
run_check jcodemunch-scope
run_check claude-md-sync
run_check env-placeholders

# ── summary ──────────────────────────────────────────────────────────────────

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

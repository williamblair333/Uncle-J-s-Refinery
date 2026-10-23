#!/usr/bin/env bash
# refinery-doctor.sh — config schema drift detection and repair.
#
# Checks for .env key renames, stack MCP servers shadowed by a
# local/project scope, a missing jcodemunch compaction-restore hook, the
# jdocmunch-watch summaries-off drop-in, CLAUDE.md drift, and placeholder values. Distinct from healthcheck.sh (runtime health).
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
    # jcodemunch-scope was generalised to mcp-scope; keep the old name working.
    [[ "$ONLY_CHECK" == jcodemunch-scope ]] && ONLY_CHECK=mcp-scope
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

# A local- or project-scope entry for a stack server shadows the user-scope one for
# that project (local > project > user), so a stale copy silently runs an old command
# or a dead path there. `claude mcp list` prints no scope (the old jcodemunch-only
# grep for "local" in it could never match); `claude mcp get <name>` prints the
# winning one ("Scope: Local config ..."), so ask it per server, from the stack repo
# and from the directory the doctor was run in.
STACK_MCP_SERVERS="jcodemunch jdatamunch jdocmunch serena duckdb"

check_mcp_scope() {
    step "mcp-scope — stack servers registered only at user scope"
    if ! command -v claude &>/dev/null; then
        info "claude binary not found — skipping"
        return
    fi
    local dirs=("$REPO_ROOT") found="" dir name scope out
    [[ "$PWD" != "$REPO_ROOT" ]] && dirs+=("$PWD")
    for dir in "${dirs[@]}"; do
        for name in $STACK_MCP_SERVERS; do
            out=$(cd "$dir" && claude mcp get "$name" 2>/dev/null) || continue
            scope=$(printf '%s\n' "$out" | sed -nE 's/^[[:space:]]*Scope:[[:space:]]*(Local|Project).*/\1/p' | head -n 1)
            [[ -n "$scope" ]] && found+="${scope,,}"$'\t'"$dir"$'\t'"$name"$'\n'
        done
    done
    found="${found%$'\n'}"

    if [[ -z "$found" ]]; then
        ok "no local/project entry shadows a stack server ($STACK_MCP_SERVERS)"
        return
    fi

    while IFS=$'\t' read -r scope dir name; do
        migration "$name registered at $scope scope in $dir (shadows user scope there)"
        suggest "run: (cd '$dir' && claude mcp remove $name -s $scope)"
    done <<< "$found"
    record_migration "mcp-scope"

    if [[ "$FIX_MODE" == true ]]; then
        while IFS=$'\t' read -r scope dir name; do
            (cd "$dir" && claude mcp remove "$name" -s "$scope" >/dev/null 2>&1) \
                && fixed "removed $name from $scope scope in $dir" \
                || info "claude mcp remove $name -s $scope (in $dir) exited non-zero"
        done <<< "$found"
    fi
}

# jdocmunch-watch summaries-off drop-in (upstream jdocmunch-mcp#120). healthcheck.sh
# asserts the effective ExecStart; this restores the file. Not applicable (ok) when the
# watcher unit isn't installed.
check_jdocmunch_watch_dropin() {
    step "jdocmunch-watch-dropin — watcher runs with --no-ai-summaries"
    local helper="$SCRIPT_DIR/jdocmunch-watch-dropin.sh" state
    state=$(bash "$helper" check 2>/dev/null | tail -n 1)
    case "$state" in
        no-unit) info "jdocmunch-watch unit not installed — skipping" ;;
        present) ok "--no-ai-summaries set for jdocmunch-watch" ;;
        missing)
            migration "jdocmunch-watch drop-in missing — watcher reindex would send local-only corpora to a remote summarizer"
            suggest "run: $0 --fix   # or: bash $helper install"
            record_migration "jdocmunch-watch-dropin"
            if [[ "$FIX_MODE" == true ]]; then
                state=$(bash "$helper" install | tail -n 1)
                [[ "$state" == installed ]] \
                    && fixed "wrote jdocmunch-watch drop-in, reloaded systemd" \
                    || info "drop-in install returned '${state:-nothing}'"
            fi
            ;;
        *) info "check failed (helper output: ${state:-none}) — skipping" ;;
    esac
}

# jcodemunch's compaction restore is two hooks: hook-precompact (registered by older
# `jcodemunch-mcp init`) and hook-sessionstart (added later; init merges it only on a
# re-run that also rewrites CLAUDE.md). With only the first half, nothing is restored.
# Adds just the SessionStart entry, reusing the exe string the existing hooks carry.
check_jcodemunch_sessionstart() {
    step "jcodemunch-sessionstart — compaction restore hook in ~/.claude/settings.json"
    local settings="$HOME/.claude/settings.json"
    if [[ ! -f "$settings" ]]; then
        info "settings.json not found — skipping"
        return
    fi
    local state
    state=$(python3 - "$settings" "$FIX_MODE" <<'PY'
import json, os, shutil, sys
path, fix = sys.argv[1], sys.argv[2] == "true"
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except (OSError, ValueError) as e:
    print(f"unreadable {e}")
    sys.exit(0)
hooks = data.get("hooks") or {}
cmds = [(ev, h.get("command", "")) for ev, groups in hooks.items()
        for g in groups or [] for h in g.get("hooks", [])]
if any(ev == "SessionStart" and "jcodemunch-mcp" in c and " hook-sessionstart" in c
       for ev, c in cmds):
    print("present")
    sys.exit(0)
exe = next((c.split(" hook-")[0] for _, c in cmds
            if "jcodemunch-mcp" in c and " hook-" in c), None)
if exe is None:
    print("no-jcodemunch")
    sys.exit(0)
if not fix:
    print("missing")
    sys.exit(0)
hooks.setdefault("SessionStart", []).append({
    "matcher": "compact|resume|fork",
    "hooks": [{"type": "command", "command": f"{exe} hook-sessionstart"}],
})
data["hooks"] = hooks
shutil.copy2(path, path + ".bak")
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
os.replace(tmp, path)
print("fixed")
PY
)
    case "$state" in
        present)       ok "hook-sessionstart registered" ;;
        no-jcodemunch) info "no jcodemunch hooks installed — skipping" ;;
        unreadable*)   info "settings.json ${state} — skipping" ;;
        missing|fixed)
            migration "jcodemunch hook-sessionstart missing — compaction restore never fires"
            suggest "run: $0 --fix   # adds SessionStart (compact|resume|fork) entry"
            record_migration "jcodemunch-sessionstart"
            [[ "$state" == fixed ]] && fixed "added jcodemunch hook-sessionstart (backup: ${settings}.bak)"
            ;;
        *) info "check failed (python3 output: ${state:-none}) — skipping" ;;
    esac
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

    # The installed copy legitimately diverges from the repo copy: dream.sh appends
    # an auto-generated playbook section to ~/.claude/CLAUDE.md only. Comparing whole
    # files therefore reports drift on every run and never reaches "in sync".
    # Compare only the routing-policy prefix, i.e. everything before the marker.
    #
    # MARKER IS DEFINED IN features/dreaming/dream.sh (see its `marker =` line).
    # If you change it there, change it here — the two are not linked, and a mismatch
    # silently restores the whole-file comparison and the permanent-drift bug.
    local dream_marker='## Dreaming Notes (auto-generated)'

    # Print the file up to (not including) the marker line; no marker => whole file.
    # Trailing blank lines are stripped: --fix writes "<prefix>\n<marker>...", so the
    # installed copy carries a separator blank line the repo copy has no reason to
    # have. Without this normalization the two prefixes differ by that one line and
    # the permanent-drift bug returns in a form that looks identical to a real diff.
    _policy_prefix() {
        awk -v m="$dream_marker" 'index($0, m) == 1 { exit } { print }' "$1" \
        | awk '{ l[NR] = $0 }
               END { n = NR
                     while (n > 0 && l[n] == "") n--
                     for (i = 1; i <= n; i++) print l[i] }'
    }

    local repo_sum installed_sum
    repo_sum=$(_policy_prefix "$repo_src" | $sum_cmd | awk '{print $1}')
    installed_sum=$(_policy_prefix "$installed" | $sum_cmd | awk '{print $1}')

    if [[ "$repo_sum" == "$installed_sum" ]]; then
        ok "in sync (routing policy; Dreaming Notes excluded)"
        return
    fi

    migration "~/.claude/CLAUDE.md routing policy differs from repo (repo: ${repo_sum:0:12}… installed: ${installed_sum:0:12}…)"
    suggest "run: $0 --fix   # replaces policy prefix, preserves Dreaming Notes"
    # .claude/settings.json excludes the repo copy from auto-load (claudeMdExcludes) so
    # sessions here don't pay for the policy twice. They therefore run on the
    # INSTALLED copy: drift here means this repo's own sessions are on the old policy.
    info "sessions in this repo load only ~/.claude/CLAUDE.md (claudeMdExcludes) — fix the drift"
    record_migration "claude-md-sync"

    if [[ "$FIX_MODE" == true ]]; then
        cp "$installed" "${installed}.bak"
        # Rebuild as: repo policy prefix + the installed copy's Dreaming Notes tail.
        # A plain `cp repo_src installed` would discard playbooks that exist nowhere else.
        local tmp
        tmp=$(mktemp "${installed}.XXXXXX") || { info "mktemp failed — skipping fix"; return; }
        _policy_prefix "$repo_src" > "$tmp"
        if grep -qF "$dream_marker" "$installed"; then
            printf '\n' >> "$tmp"
            awk -v m="$dream_marker" 'index($0, m) == 1 { f = 1 } f' "$installed" >> "$tmp"
        fi
        mv "$tmp" "$installed"
        fixed "updated ~/.claude/CLAUDE.md policy prefix, Dreaming Notes preserved (backup: ${installed}.bak)"
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
run_check mcp-scope
run_check jcodemunch-sessionstart
run_check jdocmunch-watch-dropin
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

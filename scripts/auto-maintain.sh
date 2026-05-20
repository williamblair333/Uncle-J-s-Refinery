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

# ── GitHub helpers ────────────────────────────────────────────────────────────
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

# ── Part C: auto-commit untracked global-skills files ────────────────────────
info "=== Part C: Untracked global-skills check ==="

UNTRACKED=$(git -C "$PROJ_ROOT" status --porcelain 2>/dev/null \
    | grep "^?? global-skills/" | sed 's/^?? //' | sed 's|/$||' || true)

SKILL_NAMES=()
SKILL_DESCRIPTIONS=()

if [[ -z "$UNTRACKED" ]]; then
    info "No untracked global-skills files."
else
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
            SKILL_LIST=""
            for i in "${!SKILL_NAMES[@]}"; do
                SKILL_LIST="${SKILL_LIST}"$'\n'"- \`${SKILL_NAMES[$i]}\` — ${SKILL_DESCRIPTIONS[$i]}"
            done

            python3 - "$PROJ_ROOT/CHANGELOG.md" "$TODAY" "$SKILL_LIST" << 'PYEOF'
import sys, pathlib
changelog, today, skill_list = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(changelog)
content = p.read_text()
insert_after = content.find('\n---\n')
if insert_after == -1:
    insert_after = content.find('\n\n')
entry = f"\n## {today} — auto-maintained: new skills committed\n\n### New skills\n{skill_list}\n\n---\n"
new_content = content[:insert_after+5] + entry + content[insert_after+5:]
p.write_text(new_content)
PYEOF

            sed -i "s/^\*Last updated: .*\*/*Last updated: $TODAY*/" "$PROJ_ROOT/HANDOFF.md"

            git -C "$PROJ_ROOT" add global-skills/ CHANGELOG.md HANDOFF.md
            COUNT="${#SKILL_NAMES[@]}"
            git -C "$PROJ_ROOT" commit -m "feat: auto-commit ${COUNT} new global skill(s): ${SKILL_NAMES[*]}" \
                --author="Uncle J Auto-Maintain <auto@uncle-j.local>" || \
                info "git commit failed or nothing to commit"
            info "Skills committed."
        fi
    fi
fi

# ── Part D: pin embedding canary (first-time or after model upgrade) ─────────
info "=== Part D: Embedding canary ==="
CANARY_FILE="$HOME/.code-index/embed_canary.json"
MODEL_DIR="$HOME/.code-index/models/all-MiniLM-L6-v2"

if [[ ! -d "$MODEL_DIR" ]]; then
    info "Embedding model not downloaded — downloading now..."
    if [[ "$DRY_RUN" -eq 0 ]]; then
        "$PROJ_ROOT/.venv/bin/jcodemunch-mcp" download-model >> "$LOG" 2>&1 && \
            info "Model downloaded." || warn "Model download failed (non-fatal)"
    else
        info "DRY RUN: would run jcodemunch-mcp download-model"
    fi
fi

if [[ ! -f "$CANARY_FILE" ]]; then
    info "Embedding canary not yet pinned — pinning baseline..."
    if [[ "$DRY_RUN" -eq 1 ]]; then
        info "DRY RUN: would pin embedding canary via claude -p"
    else
        PIN_PROMPT="Call the check_embedding_drift MCP tool with capture=true to pin the embedding canary baseline for the Uncle-J-s-Refinery repo. Do nothing else."
        if "$CLAUDE_BIN" -p "$PIN_PROMPT" >> "$LOG" 2>&1; then
            info "Embedding canary pinned."
        else
            warn "Canary pin failed (non-fatal — will retry on next auto-maintain run)"
        fi
    fi
else
    info "Embedding canary already pinned — skipping."
fi

# ── Telegram notification ─────────────────────────────────────────────────────
if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" && "$DRY_RUN" -eq 0 ]]; then
    SUMMARY="auto-maintain: "
    [[ "$UPGRADED" -eq 1 ]] && SUMMARY+="upgraded ${PACKAGES_TO_UPGRADE[*]}. "
    [[ "${#SKILL_NAMES[@]:-0}" -gt 0 ]] && SUMMARY+="committed ${#SKILL_NAMES[@]} skill(s). "
    [[ "$UPGRADED" -eq 0 && "${#SKILL_NAMES[@]:-0}" -eq 0 ]] && SUMMARY+="nothing to do."
    source "$PROJ_ROOT/lib/notify.sh" 2>/dev/null && notify_send_text "$SUMMARY" || true
fi

info "=== auto-maintain complete ==="
exit 0

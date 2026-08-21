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

# Write to $LOG always; echo to the terminal ONLY when stdout is a tty.
#
# This used to be `... | tee -a "$LOG"`, which writes to the file AND stdout —
# and the crontab entry redirects stdout to that same file
# (`... auto-maintain.sh >> .../state/auto-maintain.log 2>&1`). Every line
# therefore landed twice; the log was 233 KB of exact pairs. The reason lives
# in `crontab -l`, not in this script, which is why the tee looked correct.
# The tty test keeps interactive runs readable without re-creating the pairing.
log() {
    local line
    line="$(printf '[%s] %s' "$(date '+%Y-%m-%d %H:%M:%S')" "$*")"
    printf '%s\n' "$line" >> "$LOG"
    [[ -t 1 ]] && printf '%s\n' "$line"
    return 0   # a non-tty must not make log() look like a failed command
}
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
)
declare -A GITHUB=(
    [jcodemunch-mcp]="jgravelle/jcodemunch-mcp"
    [jdatamunch-mcp]="jgravelle/jdatamunch-mcp"
    [jdocmunch-mcp]="jgravelle/jdocmunch-mcp"
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

# Run the upgrade, retrying exactly once if uv's cache is what failed.
#
# uv's on-disk cache is versioned, and a schema change between uv releases can
# leave behind an entry the new binary refuses to read. Observed 2026-07-31
# 03:00 on uv 0.12.0 (three days old at the time):
#
#     × Failed to read `pysqlite3 @ file:///.../pysqlite3-...-linux_x86_64.whl`
#     ├─▶ Failed to deserialize cache entry
#     ╰─▶ array had incorrect length, expected 4
#
# The wheel is a red herring — it is merely the first entry uv happened to read,
# and its marker already scopes it to linux/x86_64 so Windows never installs it.
# Re-running the identical `uv lock` by hand succeeded, twice. Nothing about the
# package, the marker, or the lockfile was wrong.
#
# Left alone this costs a whole night and then some: the job warns, exits 0, and
# does not try again for 24h — and because check_auto_maintain_runtime in
# healthcheck.sh greps only for *shell* errors, the stack can fall arbitrarily
# far behind while auto-maintain still reports itself healthy. Clearing the cache
# is the decisive repair, so do it once, loudly, and only for this signature.
#
# Output is captured rather than streamed because the signature has to be
# grepped; both attempts are appended to the log verbatim, so the record is
# strictly richer than the redirection it replaces.
run_upgrade() {
    local out rc
    out="$( (cd "$PROJ_ROOT" && uv lock $UPGRADE_FLAGS && uv sync --inexact) 2>&1 )"
    rc=$?
    printf '%s\n' "$out" >> "$LOG"
    [[ "$rc" -eq 0 ]] && return 0

    if ! printf '%s' "$out" | grep -q 'Failed to deserialize cache entry'; then
        return "$rc"
    fi

    warn "uv cache entry unreadable (uv schema change?) — clearing cache, retrying once"
    if ! (cd "$PROJ_ROOT" && uv cache clean) >> "$LOG" 2>&1; then
        warn "uv cache clean failed — not retrying"
        return "$rc"
    fi

    out="$( (cd "$PROJ_ROOT" && uv lock $UPGRADE_FLAGS && uv sync --inexact) 2>&1 )"
    rc=$?
    printf '%s\n' "$out" >> "$LOG"
    if [[ "$rc" -eq 0 ]]; then
        info "Retry after cache clean succeeded."
    else
        warn "Retry after cache clean also failed (rc=$rc)"
    fi
    return "$rc"
}

# ── Part A: threshold-based upgrade ──────────────────────────────────────────
info "=== Part A: Package freshness check ==="
PACKAGES_TO_UPGRADE=()

for pkg in jcodemunch-mcp jdatamunch-mcp jdocmunch-mcp; do
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
UPGRADE_RANGES=""
BREAKING_FLAGS=()
declare -A OLD_SHAS
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
    if [[ "$DRY_RUN" -eq 1 ]]; then
        info "DRY RUN: would run: cd $PROJ_ROOT && uv lock $UPGRADE_FLAGS && uv sync --inexact"
    else
        if run_upgrade; then
            info "Upgrade succeeded."
            UPGRADED=1
        else
            warn "Upgrade FAILED — see $LOG for details"
        fi
    fi
else
    info "All packages within threshold. No upgrade needed."
fi

# ── Part B: post-upgrade evaluation (all packages) ───────────────────────────
info "=== Part B: Post-upgrade evaluation ==="
JCODEMUNCH="$PROJ_ROOT/.venv/bin/jcodemunch-mcp"

if [[ "$UPGRADED" -eq 1 || ( "$DRY_RUN" -eq 1 && "${#PACKAGES_TO_UPGRADE[@]}" -gt 0 ) ]]; then
    for pkg in "${PACKAGES_TO_UPGRADE[@]}"; do
        old_sha="${OLD_SHAS[$pkg]:-?}"
        new_sha=$(parse_lock_sha "$pkg")

        if [[ "$old_sha" == "?" || "$old_sha" == "$new_sha" ]]; then
            info "$pkg: SHA unchanged — skipping evaluation"
            continue
        fi

        info "$pkg: evaluating upgrade ${old_sha}→${new_sha}"
        UPGRADE_RANGES+="$pkg (${old_sha}→${new_sha}), "

        commits=$(fetch_commit_log "$pkg" "$old_sha" "$new_sha")
        if [[ -z "$commits" ]]; then
            warn "$pkg: could not fetch commit log (GitHub API issue) — skipping"
            continue
        fi

        # A keyword grep cannot decide this, and pretending it can is how the
        # one real breaking change in this upgrade reached us unflagged. Both
        # failure directions were measured against the actual 1e177b0..9d720c1
        # range (239 commits):
        #
        #   False positive — unanchored `breaking` matched "unbreaking CI lint".
        #     That was the ONLY hit in 239 commits, so the single thing this
        #     gate ever reported was noise. `\b` fixes it: "unbreaking" has no
        #     word boundary before "breaking".
        #
        #   False negative — the real contract change announced itself as
        #     "content_hash stops riding every get_symbol_source response".
        #     No marker, no "breaking", no "removed". Widening to `stops` is
        #     NOT the fix: upstream uses it for ordinary bug fixes 17 times in
        #     the same range ("stops calling a valid license unlicensed"), so
        #     that trade buys one true positive for sixteen false ones.
        #
        # Nothing here parses BREAKING CHANGE footers, because fetch_commit_log
        # keeps only the subject line (see the split at its python filter) —
        # a footer is not present in $commits to be matched. Zero commits in
        # the range used one anyway, so parsing them would add cost and no
        # recall. Fix the fetch first if that ever changes.
        #
        # So this grep is demoted to a HINT that widens the prompt, and is no
        # longer the gate on whether breaking changes get considered. Recall
        # now comes from the model reading the whole log — which identified
        # v1.108.208 correctly today with no help from this regex at all.
        breaking=$(printf '%s\n' "$commits" | grep -iE '\bbreaking\b|BREAKING[ -]CHANGE|\bdeprecat|\bincompatible\b|^[a-z]+(\([^)]*\))?!:' || true)
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
KEYWORD HINT — these subjects matched a breaking-change pattern. This is a
hint, not a finding: judge each one yourself, and do not treat a match as
proof. Past matches have been false positives.
$breaking
}${jcm_tools:+
NEW JCODEMUNCH TOOLS not yet in CLAUDE.md:
$jcm_tools
}
Your tasks — do all that apply, nothing else:
1. Read the WHOLE commit log above and decide for yourself whether any change is
   caller-visible: a field that stopped being returned, a default that flipped, a
   renamed or removed argument, a response shape that changed. Do this whether or
   not the keyword hint fired — it usually will not. Subject lines here rarely say
   'breaking'; the last real one read 'X stops riding every Y response'. Where the
   log is ambiguous, check the installed package under $PROJ_ROOT/.venv rather than
   guessing from the subject.
2. If new tools or routing changes are needed: update $PROJ_ROOT/CLAUDE.md. Keep
   existing formatting and section structure. Do NOT edit ~/.claude/CLAUDE.md — on
   this host it does not exist; the repo copy is the only one, and install.sh is
   what propagates it where that path does exist.
3. If a caller-visible change is present: append a brief entry under the TOPMOST
   '## <date>' heading in $PROJ_ROOT/HANDOFF.md — that is the current session's
   section. Do not search for a heading named 'What happened'; the only literal one
   is a legacy section thousands of lines down. Format exactly:
   '- **$pkg breaking change**: <one sentence — what changed and what callers must update>'.
4. Commit ONLY the files you edited, staged by explicit path — 'git add CLAUDE.md
   HANDOFF.md', never 'git add -a' or '.'. uv.lock is frequently dirty here and must
   never be swept into a per-package commit: commits_behind() reads its SHAs, so a
   lock that moves under the wrong message disarms this job. Message:
   'chore: post-upgrade sync — $pkg ${old_sha}→${new_sha}'.
   Note that scripts/win/checkpoint.sh auto-commits 'chk: HH:MM:SS' after each edit,
   so pin BASE=\$(git rev-parse HEAD) BEFORE your first edit and soft-reset to that
   exact SHA before committing — a wider reset would sweep in unrelated commits.
5. If nothing requires a change, do nothing and exit cleanly.
6. If a write is blocked by a permission or guard, say so explicitly in your final
   message and name the file — a silent no-op is indistinguishable from success in
   the log, and this job cannot tell the difference.
7. END YOUR FINAL MESSAGE WITH EXACTLY ONE of these lines, alone on the last line,
   no backticks and no trailing text. This job parses it; without it the run is
   recorded as a failure:
     VERDICT: changed              — you edited and committed CLAUDE.md and/or HANDOFF.md
     VERDICT: no-change-required   — you read the log and nothing was caller-visible
     VERDICT: blocked <reason>     — you could not complete the task; say why in <reason>"

        # Two defects lived in the four lines this replaced, and the 2026-08-21
        # 03:00 run demonstrates both.
        #
        # 1. NO CWD. PROJ_ROOT is computed at the top of this script and was
        #    never used to root the agent. cron starts at $HOME, and a headless
        #    Claude session can only reach its working directory, so every path
        #    into the repo was denied — Read, Bash and every mcp__jcodemunch__*
        #    call. The agent never even got as far as the edit-surface guard.
        #    Four consecutive upgrade ranges went unanalysed this way.
        #
        # 2. EXIT 0 WAS THE WHOLE TEST. `claude -p` exits 0 for a session that
        #    did nothing, so `info "evaluation complete"` was printed directly
        #    over an agent message that opened "Blocked — nothing was written to
        #    the stack repo." Task 6 had ALREADY told the agent to announce a
        #    block, and it complied exactly; the script threw the answer away.
        #
        # Note the criterion cannot be a bare diff check: task 5 makes "nothing
        # required a change" a legitimate outcome, indistinguishable by diff
        # from a blocked one. Hence the verdict line, cross-checked against the
        # delta so `changed` cannot be claimed without evidence.
        EVAL_OUT="$(mktemp "$PROJ_ROOT/state/eval-${pkg}-XXXXXX.txt")"
        # The eval is the longest phase in the run (~2 min/package), so it is
        # the widest window for an interruption to orphan this file.
        trap 'rm -f "$EVAL_OUT"' EXIT
        BASE_SHA="$(git -C "$PROJ_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"

        # cd in a subshell: roots the agent without moving this script's cwd.
        ( cd "$PROJ_ROOT" && "$CLAUDE_BIN" -p "$EVAL_PROMPT" ) > "$EVAL_OUT" 2>&1
        eval_rc=$?
        cat "$EVAL_OUT" >> "$LOG"

        verdict="$(grep -oE '^VERDICT: (changed|no-change-required|blocked\b.*)$' "$EVAL_OUT" | tail -1)"

        # Scoped to the two files the prompt allows, by path. A bare HEAD
        # comparison would let an unrelated commit — scripts/win/checkpoint.sh
        # auto-commits 'chk: HH:MM:SS' — forge a `changed` verdict.
        touched=""
        if [[ "$BASE_SHA" != "unknown" ]]; then
            touched="$(git -C "$PROJ_ROOT" diff --name-only "$BASE_SHA"..HEAD -- CLAUDE.md HANDOFF.md 2>/dev/null)"
        fi
        touched+="$(git -C "$PROJ_ROOT" status --porcelain -- CLAUDE.md HANDOFF.md 2>/dev/null)"

        if [[ "$eval_rc" -ne 0 ]]; then
            warn "$pkg: claude -p exited $eval_rc (non-fatal) — see transcript above"
        elif [[ -z "$verdict" ]]; then
            # Failure, deliberately. A missing verdict means the contract was not
            # met, and treating that as success is the bug being fixed here.
            warn "$pkg: NO VERDICT LINE — treating as failure. Agent's closing lines:"
            warn "$pkg: $(tail -3 "$EVAL_OUT" | tr '\n' ' ')"
        elif [[ "$verdict" == VERDICT:\ blocked* ]]; then
            warn "$pkg: ${verdict#VERDICT: } — NOTHING WAS WRITTEN"
        elif [[ "$verdict" == "VERDICT: changed" && -z "$touched" ]]; then
            warn "$pkg: claimed 'changed' but CLAUDE.md/HANDOFF.md are untouched since $BASE_SHA"
        else
            info "$pkg: ${verdict#VERDICT: }"
        fi

        rm -f "$EVAL_OUT"
        trap - EXIT
    done
else
    info "No upgrade performed and no packages queued — post-upgrade evaluation skipped."
fi

# ── Part C: draft untracked global-skills for Telegram approval ──────────────
info "=== Part C: Untracked global-skills check ==="

DRAFTS_DIR="$PROJ_ROOT/state/skill-drafts"
mkdir -p "$DRAFTS_DIR"

UNTRACKED=$(git -C "$PROJ_ROOT" status --porcelain 2>/dev/null \
    | grep "^?? global-skills/" | sed 's/^?? //' | sed 's|/$||' || true)

SKILL_NAMES=()
SKILL_DRAFT_IDS=()

if [[ -z "$UNTRACKED" ]]; then
    info "No untracked global-skills files."
else
    while IFS= read -r skill_dir; do
        skill_name=$(basename "$skill_dir")
        skill_md="$PROJ_ROOT/$skill_dir/SKILL.md"
        [[ ! -f "$skill_md" ]] && continue
        SKILL_NAMES+=("$skill_name")

        if [[ "$DRY_RUN" -eq 1 ]]; then
            info "DRY RUN: would draft skill for approval: $skill_name"
            continue
        fi

        # Generate a 6-char hex ID from the skill name (stable, reproducible)
        SKILL_ID=$(printf '%s' "$skill_name" | md5sum | cut -c1-6)
        DRAFT_PATH="$DRAFTS_DIR/${SKILL_ID}-skill-draft.md"
        cp "$skill_md" "$DRAFT_PATH"
        SKILL_DRAFT_IDS+=("$SKILL_ID")
        info "Drafted: $skill_name → $DRAFT_PATH (id=$SKILL_ID)"
    done <<< "$UNTRACKED"

    if [[ "${#SKILL_NAMES[@]}" -gt 0 && "$DRY_RUN" -eq 0 ]]; then
        source "$PROJ_ROOT/lib/notify.sh" 2>/dev/null || true
        DRAFT_LIST=""
        for i in "${!SKILL_NAMES[@]}"; do
            DRAFT_LIST="${DRAFT_LIST}"$'\n'"• <b>${SKILL_NAMES[$i]}</b> — id: <code>${SKILL_DRAFT_IDS[$i]:-?}</code>"
        done
        notify_send_text "📋 <b>New skill(s) ready for review:</b>${DRAFT_LIST}

Reply <code>promote &lt;id&gt;</code> to classify and install." \
            || warn "Telegram notify failed (non-fatal)"
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
    if [[ "$UPGRADED" -eq 1 ]]; then
        if [[ -n "${UPGRADE_RANGES:-}" ]]; then
            SUMMARY+="upgraded: ${UPGRADE_RANGES%, }. "
        else
            SUMMARY+="upgraded ${PACKAGES_TO_UPGRADE[*]}. "
        fi
        [[ "${#BREAKING_FLAGS[@]}" -gt 0 ]] && SUMMARY+="⚠️ breaking changes in ${BREAKING_FLAGS[*]} — see HANDOFF.md. "
    fi
    [[ "${#SKILL_NAMES[@]}" -gt 0 ]] && SUMMARY+="drafted ${#SKILL_NAMES[@]} skill(s) for approval. "
    [[ "$UPGRADED" -eq 0 && "${#SKILL_NAMES[@]}" -eq 0 ]] && SUMMARY+="nothing to do."
    source "$PROJ_ROOT/lib/notify.sh" 2>/dev/null && notify_send_text "$SUMMARY" || true
fi

info "=== auto-maintain complete ==="
exit 0

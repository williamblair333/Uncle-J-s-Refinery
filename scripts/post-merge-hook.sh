#!/usr/bin/env bash
# git post-merge hook: detect what changed in a pull and alert the user.
# Installed by install.sh as .git/hooks/post-merge.
# Safe to re-run; exits 0 always (hook failures must not block the merge).
set -uo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$PROJ_ROOT/.env"
LOG="$PROJ_ROOT/state/post-merge.log"

mkdir -p "$PROJ_ROOT/state"
log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

# ------------------------------------------------------------------
# Collect changed files since last pull
# ------------------------------------------------------------------
CHANGED=$(git diff ORIG_HEAD HEAD --name-only 2>/dev/null) || CHANGED=""
if [[ -z "$CHANGED" ]]; then
  log "post-merge: no file changes detected, skipping."
  exit 0
fi

log "post-merge: pull landed, analyzing changes..."

# ------------------------------------------------------------------
# Categorize changes into action items
# ------------------------------------------------------------------
ACTIONS=()

# New feature install scripts that weren't present before
while IFS= read -r f; do
  if [[ "$f" =~ ^features/([^/]+)/install\.sh$ ]]; then
    feature="${BASH_REMATCH[1]}"
    # Only flag if this file was ADDED (not modified)
    if git diff ORIG_HEAD HEAD --diff-filter=A --name-only 2>/dev/null | grep -qF "$f"; then
      ACTIONS+=("🆕 New feature: <b>${feature}</b> — run: bash features/${feature}/install.sh")
    fi
  fi
done <<< "$CHANGED"

# install.sh itself changed
if echo "$CHANGED" | grep -qE "^install\.sh$"; then
  ACTIONS+=("🔧 <b>install.sh</b> updated — re-run ./install.sh to apply new setup steps")
fi

# CLAUDE.md routing policy changed
if echo "$CHANGED" | grep -qE "^CLAUDE\.md$"; then
  ACTIONS+=("📋 <b>CLAUDE.md</b> updated — copy to ~/.claude/CLAUDE.md if you use global routing")
fi

# verify.sh changed — new checks may catch config drift
if echo "$CHANGED" | grep -qE "^verify\.sh$"; then
  ACTIONS+=("✅ <b>verify.sh</b> updated — run ./verify.sh to check for new requirements")
fi

# New scripts
NEW_SCRIPTS=$(git diff ORIG_HEAD HEAD --diff-filter=A --name-only 2>/dev/null \
  | grep -E "^scripts/[^/]+\.sh$" \
  | sed 's|scripts/||' || true)
if [[ -n "$NEW_SCRIPTS" ]]; then
  NAMES=$(echo "$NEW_SCRIPTS" | tr '\n' ' ')
  ACTIONS+=("📜 New scripts: ${NAMES}— check scripts/ for wiring instructions")
fi

# ------------------------------------------------------------------
# Auto-run install-reliability.sh when skill tree or installer changed
# (silent — no user action needed; logged to post-merge.log)
# Fires before the ACTIONS early-exit so it runs even on skill-only pulls.
# ------------------------------------------------------------------
if echo "$CHANGED" | grep -qE '^(global-skills/|install-reliability\.sh)'; then
    INSTALL_REL="$PROJ_ROOT/install-reliability.sh"
    if [[ -x "$INSTALL_REL" ]]; then
        log "post-merge: skill tree changed — running install-reliability.sh..."
        bash "$INSTALL_REL" >> "$LOG" 2>&1 && \
            log "post-merge: install-reliability.sh complete" || \
            log "post-merge: install-reliability.sh failed (non-fatal)"
    fi
fi

# ------------------------------------------------------------------
# Nothing actionable
# ------------------------------------------------------------------
if [[ ${#ACTIONS[@]} -eq 0 ]]; then
  log "post-merge: no actionable changes (maintenance/docs only)."
  exit 0
fi

# ------------------------------------------------------------------
# Build message
# ------------------------------------------------------------------
N=${#ACTIONS[@]}
HEADER="⚙️ Uncle J's Refinery pull — ${N} item$([ $N -gt 1 ] && echo s) need$([ $N -eq 1 ] && echo s || echo '') attention:"
BODY=""
for action in "${ACTIONS[@]}"; do
  BODY+="• ${action}"$'\n'
done
BODY+=$'\n'"<code>cd $PROJ_ROOT && ./verify.sh</code> to check current state."

FULL_MSG="${HEADER}"$'\n\n'"${BODY}"

log "post-merge actions:"
for action in "${ACTIONS[@]}"; do log "  $action"; done

# ------------------------------------------------------------------
# Auto re-index jdocmunch when any markdown doc changed
# (silent — no user action needed; logged to post-merge.log)
# ------------------------------------------------------------------
if echo "$CHANGED" | grep -qE '\.md$'; then
    JDOCMUNCH="$PROJ_ROOT/.venv/bin/jdocmunch-mcp"
    if [[ -x "$JDOCMUNCH" ]]; then
        log "post-merge: markdown changed — re-indexing jdocmunch docs..."
        "$JDOCMUNCH" index-local --path "$PROJ_ROOT" >> "$LOG" 2>&1 && \
            log "post-merge: jdocmunch re-index complete" || \
            log "post-merge: jdocmunch re-index failed (non-fatal)"
    fi
fi

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

# ------------------------------------------------------------------
# Deliver: Telegram if configured, terminal otherwise
# ------------------------------------------------------------------
if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
  source "$PROJ_ROOT/lib/notify.sh"
  notify_send_text "$FULL_MSG" && log "post-merge: Telegram alert sent." || \
    log "post-merge: Telegram send failed — see above."
else
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  # Strip HTML tags for terminal output
  echo "$FULL_MSG" | sed 's/<[^>]*>//g'
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
fi

exit 0

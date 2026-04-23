#!/usr/bin/env bash
# features/ralph-cron/install.sh
# Interactive installer that sets up cron jobs to run scripts/ralph-cron-run.sh
# for a given PRD file.
#
# Usage:
#   bash features/ralph-cron/install.sh              # interactive install
#   bash features/ralph-cron/install.sh --list       # list installed ralph cron jobs
#   bash features/ralph-cron/install.sh --uninstall MARKER

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

source "$PROJ_ROOT/lib/feature-helpers.sh"

step() { printf '\n==> %s\n' "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }

# ── --list mode ───────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--list" ]]; then
  crontab -l 2>/dev/null | grep "uncle-j-ralph-" || echo "No ralph cron jobs installed."
  exit 0
fi

# ── --uninstall mode ──────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
  MARKER="${2:-}"
  if [[ -z "$MARKER" ]]; then
    warn "--uninstall requires a MARKER argument."
    exit 1
  fi
  if [[ "$MARKER" != uncle-j-ralph-* ]]; then
    warn "MARKER '$MARKER' does not start with 'uncle-j-ralph-' — proceeding anyway."
  fi
  remove_cron "$MARKER"
  echo "Cron job '$MARKER' removed."
  exit 0
fi

# ── Interactive install ───────────────────────────────────────────────────────

# Step 1 — Dependency check
step "Checking dependencies"
for cmd in bash python3 crontab; do
  if ! command -v "$cmd" &>/dev/null; then
    warn "$cmd not found — install it and re-run."
    exit 1
  fi
  ok "$cmd"
done

# Step 2 — Verify .env has TELEGRAM credentials (optional — warn only)
step "Checking Telegram credentials"
ENV_FILE="$PROJ_ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  GIT_COMMON="$(git -C "$PROJ_ROOT" rev-parse --git-common-dir 2>/dev/null || true)"
  if [[ -n "$GIT_COMMON" ]]; then
    MAIN_ROOT="$(cd "$GIT_COMMON/.." && pwd)"
    [[ -f "$MAIN_ROOT/.env" ]] && ENV_FILE="$MAIN_ROOT/.env"
  fi
fi
if [[ ! -f "$ENV_FILE" ]]; then
  warn ".env not found — Telegram notifications will be disabled."
else
  set -a
  # shellcheck source=../../.env
  source "$ENV_FILE"
  set +a
  ok "Loaded $ENV_FILE"
  if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
    warn "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — Telegram notifications will be disabled."
  else
    ok "Telegram credentials present"
  fi
fi

# Step 3 — Verify ralph-cron-run.sh exists
step "Verifying scripts/ralph-cron-run.sh"
RALPH_RUN_SCRIPT="$PROJ_ROOT/scripts/ralph-cron-run.sh"
if [[ ! -f "$RALPH_RUN_SCRIPT" ]]; then
  warn "ralph-cron-run.sh not found at $RALPH_RUN_SCRIPT"
  warn "Run the Task D1 script first to create it."
  exit 1
fi
ok "$RALPH_RUN_SCRIPT"

# Step 4 — Interactive prompts
step "Configuring ralph cron job"

# PRD path — re-prompt until a valid file is given
while true; do
  prompt_value "PRD file path" "" RALPH_PRD
  if [[ -z "$RALPH_PRD" ]]; then
    warn "PRD path is required."
  elif [[ ! -f "$RALPH_PRD" ]]; then
    warn "File not found: $RALPH_PRD"
  else
    ok "PRD: $RALPH_PRD"
    break
  fi
done

prompt_value "Cron schedule" "0 */6 * * *" CRON_SCHEDULE
ok "Schedule: $CRON_SCHEDULE"

prompt_value "Max iterations" "10" RALPH_MAX_ITER
ok "Max iterations: $RALPH_MAX_ITER"

prompt_value "Risk threshold" "0.65" RALPH_RISK_THRESHOLD
ok "Risk threshold: $RALPH_RISK_THRESHOLD"

RALPH_SKIP_JUDGE=""
if prompt_yes_no "Skip judge gate?" "n"; then
  RALPH_SKIP_JUDGE="1"
  ok "Skip judge: yes"
else
  ok "Skip judge: no"
fi

RALPH_DRY_RUN=""
if prompt_yes_no "Dry run mode?" "n"; then
  RALPH_DRY_RUN="1"
  ok "Dry run: yes"
else
  ok "Dry run: no"
fi

# Step 5 — Generate unique marker
PRD_SLUG="$(basename "$RALPH_PRD" .md | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/-*$//')"
MARKER="uncle-j-ralph-${PRD_SLUG}"

# Step 6 — Build cron entry
LOG_FILE="$PROJ_ROOT/state/ralph-cron.log"

ENV_VARS="RALPH_PRD=${RALPH_PRD} RALPH_MAX_ITER=${RALPH_MAX_ITER} RALPH_RISK_THRESHOLD=${RALPH_RISK_THRESHOLD}"
[[ "$RALPH_SKIP_JUDGE" == "1" ]] && ENV_VARS+=" RALPH_SKIP_JUDGE=1"
[[ "$RALPH_DRY_RUN"    == "1" ]] && ENV_VARS+=" RALPH_DRY_RUN=1"

CRON_ENTRY="${CRON_SCHEDULE} ${ENV_VARS} bash ${RALPH_RUN_SCRIPT} >> ${LOG_FILE} 2>&1"

# Step 7 — Summary + confirm
step "Summary"
echo ""
echo "  Marker:    $MARKER"
echo "  Schedule:  $CRON_SCHEDULE"
echo "  PRD:       $RALPH_PRD"
echo "  Max iter:  $RALPH_MAX_ITER"
echo "  Risk thr:  $RALPH_RISK_THRESHOLD"
echo "  Skip judge: ${RALPH_SKIP_JUDGE:-no}"
echo "  Dry run:   ${RALPH_DRY_RUN:-no}"
echo "  Log:       $LOG_FILE"
echo ""
echo "  Cron entry:"
echo "  $CRON_ENTRY"
echo ""

if ! prompt_yes_no "Install this cron job?" "y"; then
  echo "Aborted — nothing installed."
  exit 0
fi

# Step 8 — Install cron
step "Installing cron job"
install_cron "$MARKER" "$CRON_ENTRY"
ok "Cron job installed"

# Step 9 — Telegram confirmation (soft — skip if notify.sh missing)
if [[ -f "$PROJ_ROOT/lib/notify.sh" ]]; then
  source "$PROJ_ROOT/lib/notify.sh"
  PRD_BASE="$(basename "$RALPH_PRD")"
  notify_send_text "⏰ Ralph cron job installed for <code>${PRD_BASE}</code> — schedule: ${CRON_SCHEDULE}. Marker: <code>${MARKER}</code>" || true
fi

# Step 10 — Done summary
step "Done"
echo ""
echo "  Marker:    $MARKER"
echo "  Schedule:  $CRON_SCHEDULE"
echo "  PRD:       $RALPH_PRD"
echo "  Log:       $LOG_FILE"
echo ""
echo "  To list ralph cron jobs:"
echo "    bash $SCRIPT_DIR/install.sh --list"
echo ""
echo "  To uninstall:"
echo "    bash $SCRIPT_DIR/install.sh --uninstall $MARKER"
echo ""

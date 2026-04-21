#!/usr/bin/env bash
# install-guardrails.sh — installs dwarvesf/claude-guardrails on
# Linux/macOS via the upstream install.sh.
#
# The upstream installer does a jq-based deep-merge of ~/.claude/settings.json,
# preserving existing hooks (like the jCodeMunch enforcement hooks that
# install.sh puts in place).
#
# Flags:
#   --lite    install the lite variant instead of full (fewer scanners)

set -euo pipefail
STACK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VARIANT="full"
for arg in "$@"; do
    case "$arg" in
        --lite) VARIANT="lite" ;;
        --full) VARIANT="full" ;;
    esac
done

step() { printf '\n==> %s\n'  "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }
has()  { command -v "$1" >/dev/null 2>&1; }

# ── jq (required by upstream installer) ──────────────────────────────────
if ! has jq; then
    step "Installing jq (required for settings.json deep-merge)"
    if   has apt-get;  then sudo apt-get install -y jq
    elif has dnf;      then sudo dnf install -y jq
    elif has pacman;   then sudo pacman -Sy --noconfirm jq
    elif has zypper;   then sudo zypper --non-interactive install jq
    elif has brew;     then brew install jq
    else
        warn "No supported package manager found. Install jq manually, then re-run."
        exit 1
    fi
fi
ok "jq $(jq --version)"

# ── Ensure the repo is cloned ────────────────────────────────────────────
GUARDRAILS_DIR="$STACK_ROOT/claude-guardrails"
if [ ! -d "$GUARDRAILS_DIR" ]; then
    step "Cloning dwarvesf/claude-guardrails"
    if ! has git; then
        warn "git not found; run ./prerequisites.sh first"
        exit 1
    fi
    git clone --depth 1 https://github.com/dwarvesf/claude-guardrails.git "$GUARDRAILS_DIR"
fi
ok "claude-guardrails present at $GUARDRAILS_DIR"

# ── Back up settings.json before the upstream install touches it ─────────
SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
    cp "$SETTINGS" "$SETTINGS.bak.guardrails.$(date +%Y%m%d-%H%M%S)"
    ok "settings.json backed up"
fi

# ── Run the upstream installer ───────────────────────────────────────────
step "Running dwarvesf install.sh (variant: $VARIANT)"
cd "$GUARDRAILS_DIR"
if [ -f "./install.sh" ]; then
    chmod +x ./install.sh
    # Upstream install.sh takes the variant as a POSITIONAL argument
    # ("lite" or "full"), not a --flag. Default (no arg) is lite, which
    # skips the prompt-injection-defender we want. Always pass explicitly.
    ./install.sh "$VARIANT"
elif [ -d "./$VARIANT" ]; then
    # Fallback: no top-level install.sh, copy hooks manually
    warn "upstream install.sh missing; falling back to manual copy from ./$VARIANT"
    mkdir -p "$HOME/.claude/hooks"
    cp -r "./$VARIANT/"*.sh "$HOME/.claude/hooks/" 2>/dev/null || true
    warn "Manual copy complete, but settings.json was NOT merged. You'll need to add hook entries yourself."
    warn "Reference: $GUARDRAILS_DIR/$VARIANT/SETUP.md"
else
    warn "Neither install.sh nor a $VARIANT/ directory found in $GUARDRAILS_DIR"
    exit 1
fi

step "Guardrails installed"
cat <<EOF

What was added to ~/.claude/settings.json:
  - UserPromptSubmit → scan-secrets.sh (blocks pasted credentials)
  - PostToolUse (Read/WebFetch/Bash/mcp__.*) → prompt-injection-defender.sh
  - PreToolUse Bash matchers: rm -rf, pipe-to-shell, git push main,
    exfil to webhook.site/ngrok, --dangerously-skip-permissions

Verify with:
  jq '.hooks' ~/.claude/settings.json

If something looks wrong, restore the pre-install backup:
  cp ~/.claude/settings.json.bak.guardrails.YYYYMMDD-HHMMSS ~/.claude/settings.json
EOF

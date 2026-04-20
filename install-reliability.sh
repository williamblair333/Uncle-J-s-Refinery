#!/usr/bin/env bash
# install-reliability.sh — installs the reliability layer on Linux/macOS.
#
# Copies our two custom skills (prior-art-check, judge) into
# ~/.claude/skills/, and clones dwarvesf/claude-guardrails ready for
# install-guardrails.sh to consume.
#
# Superpowers and Ralph are installed separately from within Claude Code
# via /plugin install — see README.md step 6.

set -euo pipefail
STACK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$STACK_ROOT"

CLAUDE_DIR="${CLAUDE_HOME:-$HOME/.claude}"

step() { printf '\n==> %s\n'  "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }
has()  { command -v "$1" >/dev/null 2>&1; }

# ── Custom skills ────────────────────────────────────────────────────────
step "Installing custom skills to $CLAUDE_DIR/skills"
mkdir -p "$CLAUDE_DIR/skills"
for skill in prior-art-check judge; do
    src="$STACK_ROOT/skills/$skill"
    dst="$CLAUDE_DIR/skills/$skill"
    if [ ! -d "$src" ]; then
        warn "skill source missing: $src"
        continue
    fi
    mkdir -p "$dst"
    cp -r "$src/." "$dst/"
    ok "skill installed: $skill"
done

# ── Clone dwarvesf/claude-guardrails ─────────────────────────────────────
step "Installing dwarvesf/claude-guardrails"
if [ -d "$STACK_ROOT/claude-guardrails" ]; then
    ok "claude-guardrails already cloned; pulling latest"
    (cd "$STACK_ROOT/claude-guardrails" && git pull --ff-only) || warn "pull failed (non-fatal)"
else
    if ! has git; then
        warn "git not found; cannot clone claude-guardrails. Run ./prerequisites.sh first."
        exit 1
    fi
    git clone --depth 1 https://github.com/dwarvesf/claude-guardrails.git "$STACK_ROOT/claude-guardrails"
    ok "claude-guardrails cloned"
fi

step "Reliability layer: skills installed, guardrails cloned"
cat <<EOF

Next:
  1. Start Claude Code and install the two plugins:
       claude
     then inside the session:
       /plugin marketplace add anthropics/claude-code
       /plugin install superpowers@claude-plugins-official
       /plugin install ralph-wiggum@anthropics-claude-code
       /reload-plugins

  2. Install guardrails (PreToolUse, UserPromptSubmit, PostToolUse hooks):
       ./install-guardrails.sh

  3. (Optional) Langfuse observability:
       ./install-langfuse.sh

Documentation:
  docs/RELIABILITY.md — how each piece fits together and when to turn it off.
EOF

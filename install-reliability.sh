#!/usr/bin/env bash
# install-reliability.sh — installs the reliability layer on Linux/macOS.
#
# Copies our four custom skills (prior-art-check, judge, outcomes,
# orchestrator) into ~/.claude/skills/ as they become available, and
# clones dwarvesf/claude-guardrails ready for
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
if [ ! -d "$STACK_ROOT/global-skills" ]; then
    warn "global-skills/ directory not found — no skills will be installed"
fi
for skill in prior-art-check judge outcomes orchestrator per-task-review-cycle post-upgrade-mcp-integration; do
    src="$STACK_ROOT/global-skills/$skill"
    dst="$CLAUDE_DIR/skills/$skill"
    if [ ! -d "$src" ]; then
        warn "skill source missing (will install when created): $src"
        continue
    fi
    if [ -L "$dst" ] && [ "$(readlink -f "$dst")" = "$(readlink -f "$src")" ]; then
        ok "skill already linked: $skill"
        continue
    fi
    rm -rf "$dst"
    ln -sfn "$src" "$dst"
    ok "skill installed: $skill"
done

# ── Write OUTCOMES_MAX_ITERATIONS to settings.json ───────────────────────────
step "Ensuring OUTCOMES_MAX_ITERATIONS in $CLAUDE_DIR/settings.json"
python3 - "$CLAUDE_DIR/settings.json" << 'PYPATCH'
import sys, json, pathlib
p = pathlib.Path(sys.argv[1])
d = json.loads(p.read_text()) if p.exists() else {}
env = d.setdefault("env", {})
if "OUTCOMES_MAX_ITERATIONS" not in env:
    env["OUTCOMES_MAX_ITERATIONS"] = "5"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2))
    print("  OK  OUTCOMES_MAX_ITERATIONS=5 written to settings.json")
else:
    print(f"  OK  OUTCOMES_MAX_ITERATIONS already set ({env['OUTCOMES_MAX_ITERATIONS']})")
PYPATCH

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

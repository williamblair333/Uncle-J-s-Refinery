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
for src in "$STACK_ROOT/global-skills"/*/; do
    [ -d "$src" ] || continue
    skill_name=$(basename "$src")
    dst="$CLAUDE_DIR/skills/$skill_name"
    if [ -L "$dst" ] && [ "$(readlink -f "$dst")" = "$(readlink -f "$src")" ]; then
        ok "skill already linked: $skill_name"
        continue
    fi
    rm -rf "$dst"
    ln -sfn "$src" "$dst"
    ok "skill installed: $skill_name"
done

# ── Agents ───────────────────────────────────────────────────────────────────
step "Installing agents to $CLAUDE_DIR/agents"
mkdir -p "$CLAUDE_DIR/agents"
if [ ! -d "$STACK_ROOT/global-agents" ]; then
    warn "global-agents/ directory not found — no agents will be installed"
else
    for src in "$STACK_ROOT/global-agents"/*.md; do
        [ -f "$src" ] || continue
        agent_name=$(basename "$src")
        dst="$CLAUDE_DIR/agents/$agent_name"
        if [ -L "$dst" ] && [ "$(readlink -f "$dst")" = "$(readlink -f "$src")" ]; then
            ok "agent already linked: $agent_name"
            continue
        fi
        rm -f "$dst"
        ln -sfn "$src" "$dst"
        ok "agent installed: $agent_name"
    done
fi

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

# ── Discipline hooks (edit-surface-guard, grep-guard) ────────────────────
step "Installing discipline hooks to $CLAUDE_DIR/hooks/discipline"
mkdir -p "$CLAUDE_DIR/hooks/discipline"
if [ ! -d "$STACK_ROOT/hooks/discipline" ]; then
    warn "hooks/discipline/ not found in repo — skipping discipline hook install"
else
    for hook_src in "$STACK_ROOT/hooks/discipline/"*.sh; do
        [ -f "$hook_src" ] || continue
        hook_name=$(basename "$hook_src")
        dst="$CLAUDE_DIR/hooks/discipline/$hook_name"
        rm -f "$dst"
        ln -sfn "$(readlink -f "$hook_src")" "$dst"
        chmod +x "$hook_src"
        ok "discipline hook linked: $hook_name"
    done

    # Wire PreToolUse hooks if not already present
    _settings="$CLAUDE_DIR/settings.json"
    if [ -f "$_settings" ]; then
        _already=$(jq '[.hooks.PreToolUse[]?.hooks[]?.command // ""] | map(select(contains("discipline"))) | length' "$_settings" 2>/dev/null || echo 0)
        if [ "$_already" -eq 0 ]; then
            _tmp=$(mktemp)
            jq '
              .hooks.PreToolUse += [
                {"matcher":"Edit|Write","hooks":[{"type":"command","command":"bash ~/.claude/hooks/discipline/edit-surface-guard.sh","timeout":10}]},
                {"matcher":"Bash","hooks":[{"type":"command","command":"bash ~/.claude/hooks/discipline/grep-guard.sh","timeout":10}]}
              ]
            ' "$_settings" > "$_tmp" \
              && jq -e '.hooks.PreToolUse | length > 0' "$_tmp" >/dev/null \
              && mv "$_tmp" "$_settings" \
              && ok "discipline PreToolUse hooks wired into settings.json" \
              || { warn "jq transform failed — settings.json unchanged"; rm -f "$_tmp"; }
        else
            ok "discipline PreToolUse hooks already wired in settings.json"
        fi

        # Wire Stop hook (unpushed-warn) if not already present
        _stop_already=$(jq '[.hooks.Stop[]?.hooks[]?.command // ""] | map(select(contains("unpushed"))) | length' "$_settings" 2>/dev/null || echo 0)
        if [ "$_stop_already" -eq 0 ]; then
            _tmp=$(mktemp)
            jq '
              .hooks.Stop += [
                {"hooks":[{"type":"command","command":"bash ~/.claude/hooks/discipline/unpushed-warn.sh","timeout":8}]}
              ]
            ' "$_settings" > "$_tmp" \
              && jq -e '.hooks.Stop | length > 0' "$_tmp" >/dev/null \
              && mv "$_tmp" "$_settings" \
              && ok "unpushed-warn Stop hook wired into settings.json" \
              || { warn "jq transform failed — settings.json unchanged"; rm -f "$_tmp"; }
        else
            ok "unpushed-warn Stop hook already wired in settings.json"
        fi
    else
        warn "settings.json not found — run install-guardrails.sh first, then re-run this script"
    fi
fi

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

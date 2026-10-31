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
#
# Config drift: bash scripts/refinery-doctor.sh [--fix]

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

# ── Prune stale skill symlinks (targets removed from global-skills) ───────────
for link in "$CLAUDE_DIR/skills"/*; do
    [ -L "$link" ] || continue   # only symlinks; leave real dirs alone
    [ -e "$link" ] && continue   # target still exists — keep
    rm -f "$link"
    ok "removed stale skill symlink: $(basename "$link")"
done

# ── Cross-harness skills ─────────────────────────────────────────────────────
# ~/.agents/skills (Codex, Copilot CLI, Gemini CLI) and ~/.gemini/skills (Antigravity).
# skill-link.sh never replaces a real directory there; it only manages its own links.
step "Linking global skills into ~/.agents/skills and ~/.gemini/skills"
bash "$STACK_ROOT/scripts/skill-link.sh" link
for dest in "$HOME/.agents/skills" "$HOME/.gemini/skills"; do
    missing_agents=0
    for src in "$STACK_ROOT/global-skills"/*/; do
        [ -d "$src" ] || continue
        [ -e "$dest/$(basename "$src")" ] || missing_agents=$((missing_agents + 1))
    done
    if [ "$missing_agents" -eq 0 ]; then
        ok "global skills linked into $dest"
    else
        warn "$missing_agents global skill(s) not linked into $dest (a real dir or foreign link has the name, or linking failed)"
    fi
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
    # Prune links to agents dropped from global-agents/ (five were, 2026-10-23).
    # Only dangling symlinks that point into global-agents/ are touched; a user's
    # own agent files and links elsewhere are left alone.
    for dst in "$CLAUDE_DIR/agents"/*.md; do
        [ -L "$dst" ] && [ ! -e "$dst" ] || continue
        case "$(readlink "$dst")" in
            "$STACK_ROOT/global-agents/"*) rm -f "$dst"; ok "agent removed (dropped upstream): $(basename "$dst")" ;;
        esac
    done
fi

# ── Workflows ────────────────────────────────────────────────────────────────
step "Installing workflows to $CLAUDE_DIR/workflows"
mkdir -p "$CLAUDE_DIR/workflows"
for src in "$STACK_ROOT/global-workflows"/*.js; do
    [ -f "$src" ] || continue
    wf_name=$(basename "$src")
    dst="$CLAUDE_DIR/workflows/$wf_name"
    if [ -L "$dst" ] && [ "$(readlink -f "$dst")" = "$(readlink -f "$src")" ]; then
        ok "workflow already linked: $wf_name"
        continue
    fi
    # Replace only a plain file identical to the repo copy; anything else (a different file,
    # a link elsewhere, a directory) is someone's local work and is left alone.
    if [ -e "$dst" ] || [ -L "$dst" ]; then
        if [ -L "$dst" ] || ! [ -f "$dst" ] || ! cmp -s "$dst" "$src"; then
            warn "workflow $wf_name exists and is not the repo copy — left alone; reconcile by hand"
            continue
        fi
    fi
    rm -f "$dst"
    ln -sfn "$src" "$dst"
    ok "workflow installed: $wf_name"
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

# ── Pre-mortem guard hooks (surface-write-guard) ─────────────────────────
# Separate from discipline/ on purpose: these are registered in settings.json
# under ~/.claude/hooks/pre-mortem-guard/, so the symlink must land on that
# exact path. Linking them into discipline/ instead would create a second,
# unregistered copy while the live one kept running unchanged.
#
# surface-write-guard.sh was a real file here for months — outside install.sh
# and refinery-doctor --fix, so it was lost on a machine rebuild and no PR
# could reach its defects. This section is what makes it versioned.
#
# Existing real files are replaced by symlinks. Content is preserved in git, so
# nothing is lost; verify afterwards with:
#   ls -l ~/.claude/hooks/pre-mortem-guard/
step "Installing pre-mortem guard hooks to $CLAUDE_DIR/hooks/pre-mortem-guard"
mkdir -p "$CLAUDE_DIR/hooks/pre-mortem-guard"
if [ ! -d "$STACK_ROOT/hooks/pre-mortem-guard" ]; then
    warn "hooks/pre-mortem-guard/ not found in repo — skipping"
else
    for hook_src in "$STACK_ROOT/hooks/pre-mortem-guard/"*.sh; do
        [ -f "$hook_src" ] || continue
        hook_name=$(basename "$hook_src")
        dst="$CLAUDE_DIR/hooks/pre-mortem-guard/$hook_name"
        rm -f "$dst"
        ln -sfn "$(readlink -f "$hook_src")" "$dst"
        chmod +x "$hook_src"
        ok "pre-mortem guard linked: $hook_name"
    done
fi

# ── Discipline hooks (edit-surface-guard, grep-guard, push-guard, offload-check, self-work-budget) ──
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
                {"matcher":"Bash","hooks":[{"type":"command","command":"bash ~/.claude/hooks/discipline/grep-guard.sh","timeout":10}]},
                {"matcher":"Bash","hooks":[{"type":"command","command":"bash ~/.claude/hooks/discipline/push-guard.sh","timeout":10}]}
              ]
            ' "$_settings" > "$_tmp" \
              && jq -e '.hooks.PreToolUse | length > 0' "$_tmp" >/dev/null \
              && mv "$_tmp" "$_settings" \
              && ok "discipline PreToolUse hooks wired into settings.json" \
              || { warn "jq transform failed — settings.json unchanged"; rm -f "$_tmp"; }
        else
            ok "discipline PreToolUse hooks already wired in settings.json"
        fi

        # Wire credential-guard (all tools) on its own key: the block above skips once any
        # discipline hook exists, so hosts installed before this guard would never get it.
        # `|| exit 1` is load-bearing: a broken guard (bash exits 2 on a syntax error, and
        # 2 means "block") must fail open and loud, never lock every tool out of a session.
        _cred_already=$(jq '[.hooks.PreToolUse[]?.hooks[]?.command // ""] | map(select(contains("credential-guard"))) | length' "$_settings" 2>/dev/null || echo 0)
        if [ "$_cred_already" -eq 0 ]; then
            _tmp=$(mktemp)
            jq '
              .hooks.PreToolUse += [
                {"matcher":"*","hooks":[{"type":"command","command":"bash ~/.claude/hooks/discipline/credential-guard.sh || exit 1","timeout":10}]}
              ]
            ' "$_settings" > "$_tmp" \
              && jq -e '.hooks.PreToolUse | length > 0' "$_tmp" >/dev/null \
              && mv "$_tmp" "$_settings" \
              && ok "credential-guard PreToolUse hook wired into settings.json" \
              || { warn "jq transform failed — settings.json unchanged"; rm -f "$_tmp"; }
        else
            ok "credential-guard PreToolUse hook already wired in settings.json"
        fi

        # Wire offload-check (Agent tool) on its own key, for the same reason as credential-guard.
        # `|| exit 1` keeps a broken script (bash exit 2 = block) from denying every subagent.
        _offload_already=$(jq '[.hooks.PreToolUse[]?.hooks[]?.command // ""] | map(select(contains("offload-check"))) | length' "$_settings" 2>/dev/null || echo 0)
        if [ "$_offload_already" -eq 0 ]; then
            _tmp=$(mktemp)
            jq '
              .hooks.PreToolUse += [
                {"matcher":"Agent","hooks":[{"type":"command","command":"bash ~/.claude/hooks/discipline/offload-check.sh || exit 1","timeout":10}]}
              ]
            ' "$_settings" > "$_tmp" \
              && jq -e '.hooks.PreToolUse | length > 0' "$_tmp" >/dev/null \
              && mv "$_tmp" "$_settings" \
              && ok "offload-check PreToolUse hook wired into settings.json" \
              || { warn "jq transform failed — settings.json unchanged"; rm -f "$_tmp"; }
        else
            ok "offload-check PreToolUse hook already wired in settings.json"
        fi

        # Wire self-work-budget on its own key, for the same reason as credential-guard.
        # `|| exit 1` keeps a broken script (bash exit 2 = block) from denying every tool.
        _budget_already=$(jq '[.hooks.PreToolUse[]?.hooks[]?.command // ""] | map(select(contains("self-work-budget"))) | length' "$_settings" 2>/dev/null || echo 0)
        if [ "$_budget_already" -eq 0 ]; then
            _tmp=$(mktemp)
            jq '
              .hooks.PreToolUse += [
                {"matcher":"Read|Edit|Write|MultiEdit|NotebookEdit|Bash|Grep|Glob|mcp__delegate__.*|mcp__ask_local__.*","hooks":[{"type":"command","command":"bash ~/.claude/hooks/discipline/self-work-budget.sh || exit 1","timeout":10}]}
              ]
            ' "$_settings" > "$_tmp" \
              && jq -e '.hooks.PreToolUse | length > 0' "$_tmp" >/dev/null \
              && mv "$_tmp" "$_settings" \
              && ok "self-work-budget PreToolUse hook wired into settings.json" \
              || { warn "jq transform failed — settings.json unchanged"; rm -f "$_tmp"; }
        else
            ok "self-work-budget PreToolUse hook already wired in settings.json"
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

        # Wire workaround-scan Stop hook on its own key, for the same reason as credential-guard.
        # It blocks a stop once per turn; `|| exit 0` makes a broken script never block one.
        _scan_already=$(jq '[.hooks.Stop[]?.hooks[]?.command // ""] | map(select(contains("workaround-scan"))) | length' "$_settings" 2>/dev/null || echo 0)
        if [ "$_scan_already" -eq 0 ]; then
            _tmp=$(mktemp)
            jq '
              .hooks.Stop += [
                {"hooks":[{"type":"command","command":"bash ~/.claude/hooks/discipline/workaround-scan.sh || exit 0","timeout":10}]}
              ]
            ' "$_settings" > "$_tmp" \
              && jq -e '.hooks.Stop | length > 0' "$_tmp" >/dev/null \
              && mv "$_tmp" "$_settings" \
              && ok "workaround-scan Stop hook wired into settings.json" \
              || { warn "jq transform failed — settings.json unchanged"; rm -f "$_tmp"; }
        else
            ok "workaround-scan Stop hook already wired in settings.json"
        fi

        # Wire self-check Stop hook: forces one evidence-backed check pass on long replies
        # (scripts/self_check.py). Same once-per-turn, fail-open shape as workaround-scan.
        _sc_already=$(jq '[.hooks.Stop[]?.hooks[]?.command // ""] | map(select(contains("self-check.sh"))) | length' "$_settings" 2>/dev/null || echo 0)
        if [ "$_sc_already" -eq 0 ]; then
            _tmp=$(mktemp)
            jq '
              .hooks.Stop += [
                {"hooks":[{"type":"command","command":"bash ~/.claude/hooks/discipline/self-check.sh || exit 0","timeout":10}]}
              ]
            ' "$_settings" > "$_tmp" \
              && jq -e '.hooks.Stop | length > 0' "$_tmp" >/dev/null \
              && mv "$_tmp" "$_settings" \
              && ok "self-check Stop hook wired into settings.json" \
              || { warn "jq transform failed — settings.json unchanged"; rm -f "$_tmp"; }
        else
            ok "self-check Stop hook already wired in settings.json"
        fi
    else
        warn "settings.json not found — run install-guardrails.sh first, then re-run this script"
    fi
fi

# ── jdocmunch-watch summaries-off drop-in ────────────────────────────────
# Lives outside the repo in ~/.config/systemd/user/jdocmunch-watch.service.d/, so a
# machine rebuild lost it with nothing to restore it (healthcheck only reported it).
# Not applicable until the watcher unit exists; never replaces an existing drop-in
# that already sets the flag. refinery-doctor --fix restores it the same way.
step "Ensuring jdocmunch-watch runs with --no-ai-summaries"
_dropin_state=$(bash "$STACK_ROOT/scripts/jdocmunch-watch-dropin.sh" install | tail -n 1) || _dropin_state="error"
case "$_dropin_state" in
    no-unit)   ok "jdocmunch-watch unit not installed — nothing to do" ;;
    present)   ok "jdocmunch-watch drop-in already present" ;;
    installed) ok "jdocmunch-watch drop-in written, systemd reloaded" ;;
    *)         warn "jdocmunch-watch drop-in install failed ($_dropin_state) — run: bash scripts/jdocmunch-watch-dropin.sh install" ;;
esac

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

# ── Claude plugins (superpowers, ralph-loop) ───────────────────────────────
step "Installing Claude plugins (superpowers, ralph-loop)"
if ! has claude; then
    warn "claude CLI not found — plugins NOT installed. After installing Claude Code, run:"
    warn "  claude plugin marketplace add anthropics/claude-code"
    warn "  claude plugin install superpowers@claude-plugins-official --scope user"
    warn "  claude plugin install ralph-loop@claude-code-plugins --scope user"
else
    _mkts_json="${CLAUDE_DIR}/plugins/known_marketplaces.json"
    _plugins_json="${CLAUDE_DIR}/plugins/installed_plugins.json"

    # Register claude-code-plugins marketplace (for ralph-loop)
    if [ ! -f "$_mkts_json" ] || ! jq -e '.["claude-code-plugins"]' "$_mkts_json" >/dev/null 2>&1; then
        claude plugin marketplace add anthropics/claude-code >/dev/null 2>&1 \
            && ok "marketplace registered: claude-code-plugins" \
            || warn "FAIL: could not register claude-code-plugins marketplace"
    else
        ok "marketplace already registered: claude-code-plugins"
    fi

    # Register claude-plugins-official marketplace (for superpowers)
    if [ ! -f "$_mkts_json" ] || ! jq -e '.["claude-plugins-official"]' "$_mkts_json" >/dev/null 2>&1; then
        claude plugin marketplace add anthropics/claude-plugins-official >/dev/null 2>&1 \
            && ok "marketplace registered: claude-plugins-official" \
            || warn "FAIL: could not register claude-plugins-official marketplace"
    else
        ok "marketplace already registered: claude-plugins-official"
    fi

    # Install superpowers at user scope if not already
    _sp_user=0
    [ -f "$_plugins_json" ] && _sp_user=$(jq -r '(.plugins["superpowers@claude-plugins-official"] // []) | map(select(.scope == "user")) | length' "$_plugins_json" 2>/dev/null || echo 0)
    if [ "$_sp_user" -eq 0 ]; then
        claude plugin install superpowers@claude-plugins-official --scope user >/dev/null 2>&1 || true
        _sp_verify=$(jq -r '(.plugins["superpowers@claude-plugins-official"] // []) | map(select(.scope == "user")) | length' "$_plugins_json" 2>/dev/null || echo 0)
        [ "$_sp_verify" -gt 0 ] && ok "plugin installed (user scope): superpowers" || warn "FAIL: superpowers install did not register — run /plugin install superpowers@claude-plugins-official manually"
    else
        ok "plugin already installed (user scope): superpowers"
    fi

    # Install ralph-loop at user scope if not already
    _rw_user=0
    [ -f "$_plugins_json" ] && _rw_user=$(jq -r '(.plugins["ralph-loop@claude-code-plugins"] // []) | map(select(.scope == "user")) | length' "$_plugins_json" 2>/dev/null || echo 0)
    if [ "$_rw_user" -eq 0 ]; then
        # `|| true`: under set -e a failed install (e.g. a renamed plugin) aborted the whole
        # installer before the warn below could say why; ralph-wiggum → ralph-loop did, 2026-10-31
        claude plugin install ralph-loop@claude-code-plugins --scope user >/dev/null 2>&1 || true
        _rw_verify=$(jq -r '(.plugins["ralph-loop@claude-code-plugins"] // []) | map(select(.scope == "user")) | length' "$_plugins_json" 2>/dev/null || echo 0)
        [ "$_rw_verify" -gt 0 ] && ok "plugin installed (user scope): ralph-loop" || warn "FAIL: ralph-loop install did not register — run /plugin install ralph-loop@claude-code-plugins manually"
    else
        ok "plugin already installed (user scope): ralph-loop"
    fi
fi

step "Reliability layer: skills, agents, guardrails, and plugins installed"
cat <<EOF

Next:
  1. Install guardrails (PreToolUse, UserPromptSubmit, PostToolUse hooks):
       ./install-guardrails.sh

  2. (Optional) Langfuse observability:
       ./install-langfuse.sh

Documentation:
  docs/RELIABILITY.md — how each piece fits together and when to turn it off.
EOF

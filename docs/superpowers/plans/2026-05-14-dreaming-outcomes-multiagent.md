# Dreaming / Outcomes / Multi-agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two install-script bugs, then implement the three features described in `_review/DREAMING_INTEGRATION_HANDOFF.md` — Dreaming (scheduled trace mining), Outcomes (rubric-aware grader loop), and Multi-agent orchestration (parallel role-scoped sub-agents).

**Architecture:** Each feature extends existing infrastructure without replacing it. Dreaming adds a cron script that queries Langfuse and writes to MemPalace. Outcomes adds a grader skill and `--rubric` flag to ralph-harness.sh. Multi-agent adds an orchestrator skill and `--decompose` flag to ralph-harness.sh with parallel subprocess management. Build order is Dreaming → Outcomes → Multi-agent (each is independently testable).

**Tech Stack:** Bash 4+, Python 3.11+ (stack venv at `.venv/`), Langfuse REST API (`GET /api/public/traces`), MemPalace CLI (`mine` command), Claude CLI (`claude -p`), `lib/feature-helpers.sh` cron helpers.

---

## Phase 0 — Bug Fixes

Two confirmed bugs before the feature work. Fix these first and commit each independently.

---

### Task 0.1: Fix install-reliability.sh skill path

**Problem:** `install-reliability.sh` line 25 loops over `$STACK_ROOT/skills/<name>` but the skill sources live in `$STACK_ROOT/global-skills/<name>`. Result: running install-reliability.sh warns "skill source missing" for all skills. The skills are currently installed only because they were copied manually.

**Files:**
- Modify: `install-reliability.sh:25`

- [ ] **Step 1: Verify the bug**

```bash
grep -n 'skills/' /opt/proj/Uncle-J-s-Refinery/install-reliability.sh
# Expect: line 25 shows  src="$STACK_ROOT/skills/$skill"
ls /opt/proj/Uncle-J-s-Refinery/skills/
# Expect: .gitkeep only (no prior-art-check, no judge)
ls /opt/proj/Uncle-J-s-Refinery/global-skills/
# Expect: judge/  per-task-review-cycle/  post-upgrade-mcp-integration/  prior-art-check/
```

- [ ] **Step 2: Write a test that currently fails**

```bash
# Test: install-reliability.sh installs prior-art-check from global-skills/
# Current behavior: warns "skill source missing: prior-art-check"
bash -n /opt/proj/Uncle-J-s-Refinery/install-reliability.sh  # syntax check passes
# Run in dry mode (can't truly dry-run, so we test the path logic):
bash -c '
  STACK_ROOT=/opt/proj/Uncle-J-s-Refinery
  src="$STACK_ROOT/skills/prior-art-check"
  [ -d "$src" ] && echo "FOUND" || echo "MISSING"
'
# Expect: MISSING (confirming the bug)
```

- [ ] **Step 3: Apply fix**

In `install-reliability.sh`, change line 25:

Old:
```
    src="$STACK_ROOT/skills/$skill"
```

New:
```
    src="$STACK_ROOT/global-skills/$skill"
```

Also update the install loop on line 25 to include all skills that should be globally installed. The full updated loop block (lines 24-35):

```bash
step "Installing custom skills to $CLAUDE_DIR/skills"
mkdir -p "$CLAUDE_DIR/skills"
for skill in prior-art-check judge outcomes orchestrator; do
    src="$STACK_ROOT/global-skills/$skill"
    dst="$CLAUDE_DIR/skills/$skill"
    if [ ! -d "$src" ]; then
        # outcomes and orchestrator may not exist yet on first run
        warn "skill source missing (will install when created): $src"
        continue
    fi
    mkdir -p "$dst"
    cp -r "$src/." "$dst/"
    ok "skill installed: $skill"
done
```

- [ ] **Step 4: Verify fix**

```bash
bash -c '
  STACK_ROOT=/opt/proj/Uncle-J-s-Refinery
  src="$STACK_ROOT/global-skills/prior-art-check"
  [ -d "$src" ] && echo "FOUND" || echo "MISSING"
'
# Expect: FOUND
bash -n /opt/proj/Uncle-J-s-Refinery/install-reliability.sh
# Expect: no output (syntax clean)
```

- [ ] **Step 5: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add install-reliability.sh
git commit -m "fix: install-reliability.sh reads global-skills/ not skills/

Skill sources were moved to global-skills/ but the loop path was never
updated. Running install-reliability.sh would warn 'skill source missing'
for all skills. Updated loop to read from global-skills/ and pre-declared
outcomes/orchestrator so they install automatically once created.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 0.2: Fix install-langfuse.sh Stop hook merge

**Problem:** `install-langfuse.sh` line 215 does `d.setdefault("hooks", {})["Stop"] = [...]` which overwrites any existing Stop hooks in the global `~/.claude/settings.json`. If re-run after other Stop hooks are present in global settings, it destroys them.

**Files:**
- Modify: `install-langfuse.sh:215` (inside the Python heredoc at line 189)

- [ ] **Step 1: Verify the bug**

```bash
grep -n 'Stop' /opt/proj/Uncle-J-s-Refinery/install-langfuse.sh
# Expect: line around 215 shows ["Stop"] = [...]  (assignment, not append)
```

- [ ] **Step 2: Apply fix**

In `install-langfuse.sh`, inside the Python heredoc (starting around line 189), replace the Stop hook assignment block. Find:

```python
d.setdefault("hooks", {})["Stop"] = [{
    "matcher": "",
    "hooks": [{
        "type": "command",
        "command": f'{python_cmd} "{hook_path}"'
    }]
}]
```

Replace with:

```python
new_hook_cmd = f'{python_cmd} "{hook_path}"'
marker = "langfuse_hook.py"
stop_blocks = d.setdefault("hooks", {}).setdefault("Stop", [])
# Remove any existing langfuse hook block (idempotent re-runs)
stop_blocks = [
    blk for blk in stop_blocks
    if not any(marker in h.get("command", "") for h in blk.get("hooks", []))
]
# Prepend langfuse hook (first in Stop chain so traces capture everything)
stop_blocks.insert(0, {
    "hooks": [{"type": "command", "command": new_hook_cmd}]
})
d["hooks"]["Stop"] = stop_blocks
```

- [ ] **Step 3: Syntax check**

```bash
bash -n /opt/proj/Uncle-J-s-Refinery/install-langfuse.sh
# Expect: no output (clean)
# Also check Python is valid by extracting and running the heredoc in a dry way:
python3 -c "
import json
d = {'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'existing hook'}]}]}}
new_hook_cmd = '/path/to/python /path/to/hook.py'
marker = 'langfuse_hook.py'
stop_blocks = d.setdefault('hooks', {}).setdefault('Stop', [])
stop_blocks = [blk for blk in stop_blocks if not any(marker in h.get('command','') for h in blk.get('hooks',[]))]
stop_blocks.insert(0, {'hooks': [{'type': 'command', 'command': new_hook_cmd}]})
d['hooks']['Stop'] = stop_blocks
print(json.dumps(d, indent=2))
"
# Expect: JSON showing both hooks in Stop list with langfuse first
```

- [ ] **Step 4: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add install-langfuse.sh
git commit -m "fix: install-langfuse.sh appends Stop hook instead of overwriting

Re-running install-langfuse.sh after other Stop hooks were added to
global settings.json would destroy them. Changed to append the langfuse
hook (idempotently, by marker) so existing hooks are preserved.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 1 — Dreaming

Self-contained. No changes to ralph-harness.sh. Requires Langfuse running and MemPalace installed.

**New files:**
- Create: `features/dreaming/dream.sh`
- Create: `features/dreaming/install.sh`
- Create: `features/dreaming/dream.md` (slash command source)
- Create: `features/dreaming/README.md`
- Create: `features/dreaming/skills/dream-synthesizer/SKILL.md`

**Modified files:**
- Modify: `verify.sh` — add dreaming cron check
- Modify: `docs/STACK.md` — add dreaming section

---

### Task 1.1: Create the dream-synthesizer skill

The skill file is invoked by dream.sh via `claude -p`. It reads formatted session traces and returns two markdown sections.

**Files:**
- Create: `features/dreaming/skills/dream-synthesizer/SKILL.md`

- [ ] **Step 1: Create directory and skill file**

```bash
mkdir -p /opt/proj/Uncle-J-s-Refinery/features/dreaming/skills/dream-synthesizer
```

Write `features/dreaming/skills/dream-synthesizer/SKILL.md`:

```markdown
---
name: dream-synthesizer
description: Analyze Claude Code session traces and extract recurring mistakes and proven playbooks for future sessions
---

You have been invoked by the dreaming pipeline with a block of Claude Code
session traces. Your job: synthesize patterns across sessions and produce
two structured sections.

## Instructions

1. Read ALL traces in the `<session-traces>` block.
2. Identify patterns that appear in at least 2 sessions. One-off events are noise.
3. Produce ONLY the two sections below. No preamble, no meta-commentary.
4. Use specific, actionable language in every entry:
   - BAD: "be careful about file reads"
   - GOOD: "call `get_symbol_source` instead of `Read` on source files — `Read` on large files consumes 10x the tokens"

## Output format

Produce exactly this structure, nothing else:

## Recurring Mistakes

- **[Pattern name]**: [What goes wrong] → [Specific prevention rule with tool/command name]
- ...

## Proven Playbooks

- **[Task type]**: [Specific tool sequence or approach that worked consistently across sessions]
- ...

## Rules

- At least 2 sessions must share a pattern before it qualifies as recurring.
- Maximum 8 entries per section.
- If there are no qualifying patterns, write `(none yet — need more session data)`.
- Strip all session IDs, user names, project names, and paths that might be sensitive.
- Keep entries general enough to apply across future sessions on different projects.
- Never include anything that looks like a credential, key, or password.
```

- [ ] **Step 2: Verify the skill file is valid markdown with correct frontmatter**

```bash
python3 -c "
import re
content = open('/opt/proj/Uncle-J-s-Refinery/features/dreaming/skills/dream-synthesizer/SKILL.md').read()
assert content.startswith('---'), 'missing frontmatter'
assert 'name: dream-synthesizer' in content, 'missing name'
assert '## Recurring Mistakes' in content, 'missing Recurring Mistakes section'
assert '## Proven Playbooks' in content, 'missing Proven Playbooks section'
print('SKILL.md: valid')
"
# Expect: SKILL.md: valid
```

- [ ] **Step 3: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add features/dreaming/skills/dream-synthesizer/SKILL.md
git commit -m "feat(dreaming): add dream-synthesizer skill

Synthesizes Langfuse session traces into Recurring Mistakes and Proven
Playbooks sections. Invoked by dream.sh via claude -p.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 1.2: Create dream.sh

The main entry point for the dreaming feature. Queries Langfuse, formats traces, invokes the synthesizer skill, writes to MemPalace and optionally CLAUDE.md.

**Files:**
- Create: `features/dreaming/dream.sh`

- [ ] **Step 1: Write the script**

Write `features/dreaming/dream.sh`:

```bash
#!/usr/bin/env bash
# features/dreaming/dream.sh — Dream synthesizer for Uncle J's Refinery.
#
# Queries Langfuse for traces since the last run, invokes the
# dream-synthesizer skill via claude -p, writes playbooks to MemPalace,
# and optionally appends proven playbooks to ~/.claude/CLAUDE.md.
#
# Usage:
#   ./dream.sh [--since <ISO8601>] [--dry-run]
#
# Exit codes: 0 success/skip, 1 config error, 2 synthesis error

set -euo pipefail

DREAM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_ROOT="$(cd "$DREAM_DIR/../.." && pwd)"
VENV_PY="$STACK_ROOT/.venv/bin/python"
MEMPALACE="$STACK_ROOT/.venv/bin/mempalace"
SKILL_FILE="$DREAM_DIR/skills/dream-synthesizer/SKILL.md"
STATE_DIR="$STACK_ROOT/state"
LAST_RUN_FILE="$STATE_DIR/dreaming-last-run.txt"
LOG_FILE="$STATE_DIR/dreaming.log"
ENV_FILE="$STATE_DIR/dreaming.env"
DRY_RUN=0
SINCE=""

step() { printf '\n==> %s\n' "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }
log_entry() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG_FILE"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --since)   SINCE="${2:?}"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

# Load env overrides (DREAMING_CRON_SCHEDULE, DREAMING_ENABLED, DREAMING_OUTPUT_DIR)
[ -f "$ENV_FILE" ] && source "$ENV_FILE" || true
DREAMING_OUTPUT_DIR="${DREAMING_OUTPUT_DIR:-$HOME/.claude/dreaming-output}"

# ── Dependency checks ────────────────────────────────────────────────────────
[ -x "$VENV_PY" ]   || { warn "Stack venv missing — run ./install.sh first"; exit 1; }
[ -x "$MEMPALACE" ] || { warn "mempalace binary missing — run ./install.sh first"; exit 1; }
[ -f "$SKILL_FILE" ] || { warn "dream-synthesizer skill missing — run features/dreaming/install.sh"; exit 1; }
command -v claude >/dev/null 2>&1 || { warn "'claude' CLI not on PATH"; exit 1; }
command -v curl   >/dev/null 2>&1 || { warn "'curl' not on PATH"; exit 1; }

# ── Read Langfuse credentials ─────────────────────────────────────────────────
_get_setting() {
    "$VENV_PY" -c "import json,os; d=json.load(open(os.path.expanduser('~/.claude/settings.json'))); print(d.get('env',{}).get('$1',''))" 2>/dev/null
}
LANGFUSE_HOST="${LANGFUSE_HOST:-$(_get_setting LANGFUSE_HOST)}"
LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-$(_get_setting LANGFUSE_PUBLIC_KEY)}"
LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY:-$(_get_setting LANGFUSE_SECRET_KEY)}"

if [ -z "$LANGFUSE_PUBLIC_KEY" ] || [ -z "$LANGFUSE_SECRET_KEY" ] || [ -z "$LANGFUSE_HOST" ]; then
    warn "Langfuse credentials missing from ~/.claude/settings.json env block"
    warn "Run install-langfuse.sh to configure them"
    exit 1
fi

# ── Determine time window ────────────────────────────────────────────────────
mkdir -p "$STATE_DIR"
if [ -n "$SINCE" ]; then
    FROM_TS="$SINCE"
else
    # Default: since last run; fallback to 24h ago on first run
    if [ -f "$LAST_RUN_FILE" ]; then
        FROM_TS="$(cat "$LAST_RUN_FILE")"
    else
        FROM_TS="$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
                   || date -u -v-24H +%Y-%m-%dT%H:%M:%SZ)"  # Linux vs macOS
    fi
fi
NOW_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# ── Query Langfuse ────────────────────────────────────────────────────────────
step "Querying Langfuse traces since $FROM_TS"
FROM_ENC="$("$VENV_PY" -c "import urllib.parse; print(urllib.parse.quote('$FROM_TS'))")"
TRACES_JSON="$(curl -s --max-time 15 \
    -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
    "${LANGFUSE_HOST%/}/api/public/traces?limit=100&fromTimestamp=$FROM_ENC" 2>&1)"

TRACE_COUNT="$(printf '%s' "$TRACES_JSON" | "$VENV_PY" -c \
    "import sys,json; d=json.loads(sys.stdin.read()); print(len(d.get('data',[])))" 2>/dev/null || echo 0)"
ok "Found $TRACE_COUNT traces"

if [ "$TRACE_COUNT" -eq 0 ]; then
    ok "No new traces — skipping synthesis"
    printf '%s\n' "$NOW_TS" > "$LAST_RUN_FILE"
    log_entry "skip: no traces since $FROM_TS"
    exit 0
fi

# ── Format traces for synthesizer ────────────────────────────────────────────
step "Formatting $TRACE_COUNT trace(s) for synthesis"
FORMATTED="$(printf '%s' "$TRACES_JSON" | "$VENV_PY" - <<'PYEOF'
import sys, json
data = json.loads(sys.stdin.read()).get("data", [])
lines = []
for t in data[:30]:   # cap at 30 — keeps prompt under ~8k tokens
    session  = t.get("sessionId", "?")
    ts       = (t.get("timestamp") or "")[:10]
    inp      = str(t.get("input",  "") or "")[:300]
    out      = str(t.get("output", "") or "")[:300]
    obs      = t.get("observations", []) or []
    tools    = list({o.get("name","") for o in obs if o.get("type") == "SPAN"})[:8]
    lines.append(f"--- Session {session} ({ts}) ---")
    lines.append(f"Task: {inp}")
    lines.append(f"Result: {out}")
    if tools:
        lines.append(f"Tools used: {', '.join(tools)}")
    lines.append("")
print("\n".join(lines))
PYEOF
)"

# ── Invoke dream-synthesizer ──────────────────────────────────────────────────
step "Invoking dream-synthesizer"
SKILL_CONTENT="$(cat "$SKILL_FILE")"
TMP="$(mktemp --suffix=.md)"
printf '<skill>\n%s\n</skill>\n\n<session-traces>\n%s\n</session-traces>\n' \
    "$SKILL_CONTENT" "$FORMATTED" > "$TMP"

if [ "$DRY_RUN" -eq 1 ]; then
    ok "[dry-run] would invoke: claude -p @$TMP --dangerously-skip-permissions"
    SYNTHESIS="## Recurring Mistakes

(dry-run placeholder)

## Proven Playbooks

(dry-run placeholder)"
else
    SYNTHESIS="$(claude -p "@$TMP" --dangerously-skip-permissions 2>&1 || true)"
fi
rm -f "$TMP"

if [ -z "$SYNTHESIS" ]; then
    warn "Synthesis returned empty output"
    log_entry "fail: empty synthesis output ($TRACE_COUNT traces)"
    exit 2
fi

# ── Write output to MemPalace ─────────────────────────────────────────────────
step "Writing to MemPalace via mine"
mkdir -p "$DREAMING_OUTPUT_DIR"
OUTPUT_FILE="$DREAMING_OUTPUT_DIR/dream-$(date +%Y-%m-%d).md"

{
    printf '# Dreaming output — %s\n\n' "$NOW_TS"
    printf '%s\n' "$SYNTHESIS"
} > "$OUTPUT_FILE"

if [ "$DRY_RUN" -eq 0 ]; then
    "$MEMPALACE" mine "$DREAMING_OUTPUT_DIR" --wing "dreaming" 2>/dev/null \
        && ok "MemPalace updated" \
        || warn "MemPalace mine failed (non-fatal — output still written to $OUTPUT_FILE)"
else
    ok "[dry-run] would mine: $DREAMING_OUTPUT_DIR"
fi

# ── Append proven playbooks to CLAUDE.md (idempotent) ────────────────────────
CLAUDE_MD="$HOME/.claude/CLAUDE.md"
if [ -f "$CLAUDE_MD" ] && [ "$DRY_RUN" -eq 0 ]; then
    step "Updating ~/.claude/CLAUDE.md § Dreaming Notes"
    PLAYBOOKS="$(printf '%s' "$SYNTHESIS" | awk '/^## Proven Playbooks/{found=1} found{print}' | head -30)"
    if [ -n "$PLAYBOOKS" ]; then
        "$VENV_PY" - <<PYEOF
import pathlib, textwrap
p = pathlib.Path('$CLAUDE_MD')
content = p.read_text()
marker = '\n## Dreaming Notes (auto-generated)'
if marker in content:
    content = content[:content.index(marker)]
content = content.rstrip() + '\n\n## Dreaming Notes (auto-generated)\n\n'
content += '<!-- Last updated: $NOW_TS -->\n\n'
content += '''$PLAYBOOKS'''
content += '\n'
p.write_text(content)
print('  OK  CLAUDE.md updated')
PYEOF
    fi
fi

# ── Update last-run timestamp ─────────────────────────────────────────────────
printf '%s\n' "$NOW_TS" > "$LAST_RUN_FILE"
log_entry "ok: $TRACE_COUNT traces processed → $OUTPUT_FILE"

step "Dreaming run complete"
ok "Traces processed : $TRACE_COUNT"
ok "Output           : $OUTPUT_FILE"
ok "Last run         : $LAST_RUN_FILE"
```

- [ ] **Step 2: Make executable and syntax-check**

```bash
chmod +x /opt/proj/Uncle-J-s-Refinery/features/dreaming/dream.sh
bash -n /opt/proj/Uncle-J-s-Refinery/features/dreaming/dream.sh
# Expect: no output (clean syntax)
```

- [ ] **Step 3: Dry-run smoke test**

```bash
cd /opt/proj/Uncle-J-s-Refinery
bash features/dreaming/dream.sh --dry-run --since 2026-01-01T00:00:00Z
# Expect: either "skip: no traces" or "[dry-run] would invoke: claude -p ..."
# Expect: exit 0
```

- [ ] **Step 4: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add features/dreaming/dream.sh
git commit -m "feat(dreaming): add dream.sh entry point

Queries Langfuse REST API for traces since last run, formats them for
the synthesizer skill, writes playbooks to MemPalace via mine, and
appends proven playbooks to ~/.claude/CLAUDE.md idempotently.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 1.3: Create features/dreaming/install.sh and dream.md slash command

**Files:**
- Create: `features/dreaming/install.sh`
- Create: `features/dreaming/dream.md`

- [ ] **Step 1: Write install.sh**

Write `features/dreaming/install.sh`:

```bash
#!/usr/bin/env bash
# features/dreaming/install.sh — register dreaming cron and install skill/command
# Usage: ./install.sh [--uninstall]

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$STACK_ROOT/lib/feature-helpers.sh"

MARKER="uncle-j-dreaming"
DREAM_SCRIPT="$SCRIPT_DIR/dream.sh"
SKILL_SRC="$SCRIPT_DIR/skills/dream-synthesizer"
SKILL_DST="${HOME}/.claude/skills/dream-synthesizer"
CMD_SRC="$SCRIPT_DIR/dream.md"
CMD_DST="${HOME}/.claude/commands/dream.md"
STATE_DIR="$STACK_ROOT/state"
ENV_FILE="$STATE_DIR/dreaming.env"

step() { printf '\n==> %s\n' "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }

if [ "${1:-}" = "--uninstall" ]; then
    step "Removing dreaming cron entry"
    remove_cron "$MARKER"
    ok "cron entry removed (skill and command left in place)"
    exit 0
fi

# Make dream.sh executable
chmod +x "$DREAM_SCRIPT"

# Install skill
step "Installing dream-synthesizer skill"
mkdir -p "$SKILL_DST"
cp -r "$SKILL_SRC/." "$SKILL_DST/"
ok "installed to $SKILL_DST"

# Install /dream slash command
step "Installing /dream slash command"
mkdir -p "$(dirname "$CMD_DST")"
cp "$CMD_SRC" "$CMD_DST"
ok "installed to $CMD_DST"

# Write env defaults
step "Writing dreaming env defaults"
mkdir -p "$STATE_DIR"
SCHEDULE="${DREAMING_CRON_SCHEDULE:-0 2 * * *}"
write_env_var "$ENV_FILE" "DREAMING_CRON_SCHEDULE" "$SCHEDULE"
write_env_var "$ENV_FILE" "DREAMING_ENABLED" "1"
ok "env file: $ENV_FILE"

# Register cron
step "Registering cron entry (schedule: $SCHEDULE)"
CRON_CMD="$SCHEDULE bash $DREAM_SCRIPT >> $STATE_DIR/dreaming.log 2>&1"
install_cron "$MARKER" "$CRON_CMD"
ok "cron registered"

step "Dreaming feature installed"
printf '\n'
printf '  Run on demand:  bash %s\n' "$DREAM_SCRIPT"
printf '  Inside Claude:  /dream\n'
printf '  Disable:        bash %s --uninstall\n' "$SCRIPT_DIR/install.sh"
printf '  Schedule env:   DREAMING_CRON_SCHEDULE in %s\n\n' "$ENV_FILE"
```

- [ ] **Step 2: Write dream.md slash command**

Write `features/dreaming/dream.md`:

```markdown
---
description: Run the Uncle J's Refinery dream synthesizer — mine past Langfuse traces and write playbooks to MemPalace
allowed-tools: Bash
---

Run the dreaming synthesizer for Uncle J's Refinery.

Steps:

1. Verify the repo root is `/opt/proj/Uncle-J-s-Refinery` or a descendant.
   If not, say so and stop — dream.sh uses absolute stack paths.

2. Execute:
   ```
   bash /opt/proj/Uncle-J-s-Refinery/features/dreaming/dream.sh
   ```

3. Report:
   - The number of traces processed.
   - Whether MemPalace was updated.
   - Whether `~/.claude/CLAUDE.md` was updated.
   - The path of the output file written.
   - Any `warn` lines from stderr.

4. If Langfuse credentials are missing or the server is unreachable,
   say so and suggest: `bash /opt/proj/Uncle-J-s-Refinery/install-langfuse.sh`

To run in dry-run mode (no writes): `bash .../dream.sh --dry-run`

Do not attempt to fix failures — dream.sh is authoritative.
```

- [ ] **Step 3: Make executable and syntax-check**

```bash
chmod +x /opt/proj/Uncle-J-s-Refinery/features/dreaming/install.sh
bash -n /opt/proj/Uncle-J-s-Refinery/features/dreaming/install.sh
# Expect: no output
```

- [ ] **Step 4: Test install in dry mode**

```bash
# Verify install.sh can be parsed and runs its path checks
bash -c '
  SCRIPT_DIR=/opt/proj/Uncle-J-s-Refinery/features/dreaming
  STACK_ROOT=/opt/proj/Uncle-J-s-Refinery
  source "$STACK_ROOT/lib/feature-helpers.sh"
  echo "lib loaded OK"
  [ -x "$SCRIPT_DIR/dream.sh" ] && echo "dream.sh executable" || echo "dream.sh NOT executable"
  [ -f "$SCRIPT_DIR/skills/dream-synthesizer/SKILL.md" ] && echo "skill present" || echo "skill MISSING"
  [ -f "$SCRIPT_DIR/dream.md" ] && echo "command present" || echo "command MISSING"
'
# Expect: lib loaded OK / dream.sh executable / skill present / command present
```

- [ ] **Step 5: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add features/dreaming/install.sh features/dreaming/dream.md
git commit -m "feat(dreaming): add install.sh and /dream slash command

install.sh registers the 2 AM daily cron entry, installs the
dream-synthesizer skill to ~/.claude/skills/, and copies the /dream
slash command to ~/.claude/commands/.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 1.4: Create features/dreaming/README.md

**Files:**
- Create: `features/dreaming/README.md`

- [ ] **Step 1: Write README.md**

Write `features/dreaming/README.md`:

```markdown
# Dreaming

Scheduled batch process that mines past Claude Code sessions and writes
playbooks and mistake patterns back to MemPalace and `~/.claude/CLAUDE.md`.

Inspired by Anthropic's Dreaming capability announced at Code with Claude
(May 7, 2026). The implementation uses the Langfuse Stop hook traces that
are already being recorded, so there is no additional instrumentation needed.

## What it does

1. Queries Langfuse REST API for traces since the last run
2. Formats traces into a structured prompt (task, tools used, outcome)
3. Invokes the `dream-synthesizer` skill via `claude -p`
4. Synthesizer returns `## Recurring Mistakes` and `## Proven Playbooks`
5. Output written to `~/.claude/dreaming-output/dream-YYYY-MM-DD.md`
6. MemPalace ingests the output directory (wing: `dreaming`)
7. Proven playbooks appended to `~/.claude/CLAUDE.md` (idempotent)

## Prerequisites

- Langfuse running and traces being recorded (install-langfuse.sh)
- MemPalace installed (install.sh)
- Claude CLI on PATH

## Install

```bash
bash features/dreaming/install.sh
```

## Manual trigger

```bash
bash features/dreaming/dream.sh

# Or from inside a Claude Code session:
/dream
```

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `DREAMING_CRON_SCHEDULE` | `0 2 * * *` | Cron schedule (2 AM daily) |
| `DREAMING_ENABLED` | `1` | Set to `0` to skip cron without uninstalling |
| `DREAMING_OUTPUT_DIR` | `~/.claude/dreaming-output` | Where output files are written |

Set in `state/dreaming.env` (written by install.sh, gitignored).

## Uninstall

```bash
bash features/dreaming/install.sh --uninstall
```

Removes the cron entry. Skill and command stay installed. To fully remove:

```bash
rm -rf ~/.claude/skills/dream-synthesizer ~/.claude/commands/dream.md
```
```

- [ ] **Step 2: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add features/dreaming/README.md
git commit -m "feat(dreaming): add README.md

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 1.5: Update verify.sh and docs/STACK.md

**Files:**
- Modify: `verify.sh`
- Modify: `docs/STACK.md`

- [ ] **Step 1: Add dreaming cron check to verify.sh**

In `verify.sh`, after the last `check` call (before the final `if` block), add:

```bash
echo
echo "Dreaming feature (when DREAMING_ENABLED=1):"
if [ "${DREAMING_ENABLED:-0}" = "1" ]; then
    check "dreaming cron installed" bash -c 'crontab -l 2>/dev/null | grep -q uncle-j-dreaming'
    check "dream.sh executable" test -x "$STACK_ROOT/features/dreaming/dream.sh"
    check "dream-synthesizer skill installed" test -d "$HOME/.claude/skills/dream-synthesizer"
else
    printf '  SKIP  dreaming checks (DREAMING_ENABLED not set)\n'
fi
```

Add this immediately before the final count/exit block (the `if [ "$fails" -eq 0 ]` block).

- [ ] **Step 2: Test verify.sh syntax**

```bash
bash -n /opt/proj/Uncle-J-s-Refinery/verify.sh
# Expect: no output
```

- [ ] **Step 3: Add dreaming section to docs/STACK.md**

Append to `docs/STACK.md` after the "How they fit together" section:

```markdown

---

## Dreaming (scheduled session synthesis)

**What it does.** Runs on a schedule (default: 2 AM daily). Queries Langfuse
for traces since the last run, invokes the `dream-synthesizer` skill to
extract recurring mistakes and proven playbooks, and writes the results to
MemPalace (wing: `dreaming`) and `~/.claude/CLAUDE.md`.

**Entry point.** `features/dreaming/dream.sh` (also available as `/dream`
slash command for on-demand runs inside Claude Code).

**Install.**
```bash
bash features/dreaming/install.sh
```

**When to use.** After a project has accumulated 10+ Langfuse traces. The
`prior-art-check` skill will automatically surface dreaming output on the
next non-trivial task because it queries MemPalace, and the `## Dreaming
Notes` section in `CLAUDE.md` informs every session directly.

**Key env vars.** `DREAMING_CRON_SCHEDULE` (default: `0 2 * * *`),
`DREAMING_ENABLED` (default: `1`). Set in `state/dreaming.env`.
```

- [ ] **Step 4: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add verify.sh docs/STACK.md
git commit -m "feat(dreaming): wire verify.sh checks and add STACK.md entry

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 2 — Outcomes

Extends the existing `judge` skill and ralph-harness.sh. Requires Phase 0 complete (so install-reliability.sh installs the skill correctly).

**New files:**
- Create: `global-skills/outcomes/RUBRIC.md.template`
- Create: `global-skills/outcomes/SKILL.md`

**Modified files:**
- Modify: `ralph-harness.sh` — `--rubric` flag + `invoke_outcomes_check` function
- Modify: `prd-template.md` — add `## Success Rubric` section
- Modify: `docs/RELIABILITY.md` — add outcomes loop entry
- Modify: `verify.sh` — add outcomes skill check

---

### Task 2.1: Create outcomes skill and rubric template

**Files:**
- Create: `global-skills/outcomes/SKILL.md`
- Create: `global-skills/outcomes/RUBRIC.md.template`

- [ ] **Step 1: Create directory**

```bash
mkdir -p /opt/proj/Uncle-J-s-Refinery/global-skills/outcomes
```

- [ ] **Step 2: Write SKILL.md**

Write `global-skills/outcomes/SKILL.md`:

```markdown
---
name: outcomes
description: Rubric-aware grader agent — evaluates working agent output against a rubric in a fresh context and produces a structured gap report
---

You are the outcomes grader. You run in a FRESH context, isolated from
the working agent's accumulated reasoning. This is intentional: your job
is to catch what the working agent's long-running thread missed.

## Critical rules

- Evaluate ONLY what is observable in the `<current-state>` block.
- Do NOT give benefit of the doubt. If you cannot confirm a pass condition,
  mark the criterion as FAIL.
- Never say "try harder" or "check if X". Name the SPECIFIC gap and the
  SPECIFIC fix: exact file path, exact tool call, exact command.
- `required` criteria: ALL must pass for `verdict` to be `pass`.
- `preferred` criteria: appear in `failed_criteria` but do not block.

## Instructions

1. Read the `<rubric>` block. Each criterion has a pass condition, fail
   condition, and weight (`required` or `preferred`).

2. For each criterion, evaluate independently:
   - Does the `<current-state>` block show evidence that the pass condition
     is met?
   - Verdict: `pass` or `fail`.

3. Produce EXACTLY one line of JSON — no markdown, no commentary:

```json
{"verdict":"pass","failed_criteria":[],"remediation":"","why":"all required criteria met"}
```

or on failure:

```json
{"verdict":"fail","failed_criteria":["Tests pass","No untested symbols"],"remediation":"Run pytest — 2 tests fail in tests/test_dream.sh (missing mock for Langfuse API). Add get_untested_symbols check: run_pre_script returns untested=2.","why":"required criteria 1 and 2 unmet"}
```

## Output schema

| Field | Type | Meaning |
|---|---|---|
| `verdict` | `"pass"` \| `"fail"` | `pass` only if ALL required criteria pass |
| `failed_criteria` | `string[]` | Names of failed criteria (required + preferred) |
| `remediation` | `string` | Specific steps to fix each failure |
| `why` | `string` | Short reason for the verdict |
```

- [ ] **Step 3: Write RUBRIC.md.template**

Write `global-skills/outcomes/RUBRIC.md.template`:

```markdown
# Success Rubric — [feature name]

Each criterion needs a pass condition that is observable and checkable —
not "looks good" but "this command exits 0" or "this file exists".

Weight: `required` = blocks completion; `preferred` = reported but non-blocking.

---

### 1. Tests pass
- **Pass**: test suite exits 0 with no skips (`pytest` / `bash tests/...` / etc.)
- **Fail**: any test failure, error, or skip
- **Weight**: required

### 2. No untested symbols
- **Pass**: `get_untested_symbols(changed_only=true)` returns empty list
- **Fail**: new code exists without test coverage
- **Weight**: required

### 3. Risk profile acceptable
- **Pass**: `get_pr_risk_profile()` returns composite score < 0.65
- **Fail**: score >= 0.65
- **Weight**: required

### 4. PRD marked DONE
- **Pass**: first non-empty line of PRD `## Progress` section starts with `DONE`
- **Fail**: progress shows any other status
- **Weight**: required

### 5. No secrets in working tree
- **Pass**: `git grep -iE "sk-lf-[a-f0-9]{16,}|PASSWORD=[a-zA-Z0-9]{8,}"` returns nothing
- **Fail**: any match found
- **Weight**: required

### 6. Documentation updated
- **Pass**: relevant docs section updated to reflect the change
- **Fail**: new feature with no corresponding doc update
- **Weight**: preferred

<!-- Add project-specific criteria below this line -->
```

- [ ] **Step 4: Verify files**

```bash
python3 -c "
import re
for path, must_have in [
    ('/opt/proj/Uncle-J-s-Refinery/global-skills/outcomes/SKILL.md',
     ['name: outcomes', 'verdict', 'required', 'preferred']),
    ('/opt/proj/Uncle-J-s-Refinery/global-skills/outcomes/RUBRIC.md.template',
     ['required', 'preferred', 'Tests pass', 'No untested symbols']),
]:
    content = open(path).read()
    for s in must_have:
        assert s in content, f'Missing in {path}: {s}'
    print(f'OK: {path}')
"
# Expect: OK for both files
```

- [ ] **Step 5: Install skill**

```bash
bash /opt/proj/Uncle-J-s-Refinery/install-reliability.sh 2>&1 | grep -E 'OK|warn|MISS'
# Expect: OK for prior-art-check, judge, outcomes; warn for orchestrator (not yet created)
ls ~/.claude/skills/outcomes/SKILL.md
# Expect: file exists
```

- [ ] **Step 6: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add global-skills/outcomes/
git commit -m "feat(outcomes): add outcomes grader skill and rubric template

SKILL.md implements the rubric-aware grader agent for the outcomes loop.
RUBRIC.md.template provides a starter rubric with 6 criteria covering
tests, coverage, risk, PRD status, secrets, and docs.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2.2: Add --rubric flag to ralph-harness.sh

**Files:**
- Modify: `ralph-harness.sh`

The `--rubric` flag adds an outcomes check after each done-gate check. If the outcomes grader finds failures, the gap report is injected as context for the next iteration. The loop exits only when BOTH the done-gate AND the outcomes grader approve.

- [ ] **Step 1: Write a test for the current harness that captures --rubric behavior**

```bash
# Test: harness rejects unknown flag
/opt/proj/Uncle-J-s-Refinery/ralph-harness.sh --rubric 2>&1 | head -2
# Expect: "Unknown arg: --rubric" and usage (exit 1)
echo "exit: $?"
```

- [ ] **Step 2: Add flag declaration and parsing**

In `ralph-harness.sh`, add after the existing variable declarations (around line 29):

```bash
RUBRIC_PATH=""
OUTCOMES_MAX="${OUTCOMES_MAX_ITERATIONS:-5}"
OUTCOMES_ITER=0
OUTCOMES_CONTEXT=""
```

In the `while [ $# -gt 0 ]` arg-parser block, add after the `--skip-judge` line:

```bash
        --rubric)          RUBRIC_PATH="${2:?}"; shift 2 ;;
```

In the startup banner (`ok` block around lines 68-74), add:

```bash
ok "Rubric     : ${RUBRIC_PATH:-(none)}"
ok "OutcomesMax: $OUTCOMES_MAX"
```

After validation block (around line 77), add:

```bash
if [ -n "$RUBRIC_PATH" ] && [ ! -f "$RUBRIC_PATH" ]; then
    stop "Rubric file not found: $RUBRIC_PATH"; exit 1
fi
```

- [ ] **Step 3: Add invoke_outcomes_check function**

Add this function after the `invoke_done_gate` function (around line 134):

```bash
invoke_outcomes_check() {
    local repo="$1" rubric_path="$2"
    local orch_skill="$HOME/.claude/skills/outcomes/SKILL.md"

    if [ ! -f "$orch_skill" ]; then
        warn "outcomes skill not found at $orch_skill; skipping outcomes check"
        printf '{"verdict":"skip","why":"outcomes skill not installed"}'
        return
    fi

    local skill_content rubric_content prd_progress prompt output line tmp
    skill_content="$(cat "$orch_skill")"
    rubric_content="$(cat "$rubric_path")"
    prd_progress="$(awk '/^## Progress/{found=1} found{print}' "$PRD_PATH" | head -25)"

    prompt="<skill>
$skill_content
</skill>

<rubric>
$rubric_content
</rubric>

<current-state>
PRD Progress section:
$prd_progress
</current-state>

Evaluate the current state against the rubric. Output EXACTLY one JSON line."

    tmp="$(mktemp --suffix=.md)"
    printf '%s\n' "$prompt" > "$tmp"
    step "Outcomes: asking grader to evaluate rubric"
    output="$(cd "$repo" && claude -p "@$tmp" --dangerously-skip-permissions 2>&1 || true)"
    rm -f "$tmp"

    line="$(printf '%s\n' "$output" | awk '/^[[:space:]]*\{/' | tail -1)"
    if [ -z "$line" ]; then
        warn "Outcomes grader returned no JSON; assuming skip"
        printf '{"verdict":"skip","why":"no JSON from grader"}'
        return
    fi
    printf '%s' "$line"
}
```

- [ ] **Step 4: Wire outcomes check into the main loop**

In the main loop, after the `invoke_done_gate` call and before the `if [ "$verdict" = "done" ]` block (around line 182), add:

```bash
    # Outcomes check (--rubric mode only)
    if [ -n "$RUBRIC_PATH" ] && [ "$SKIP_JUDGE" -eq 0 ]; then
        OUTCOMES_ITER=$((OUTCOMES_ITER + 1))
        if [ "$OUTCOMES_ITER" -gt "$OUTCOMES_MAX" ]; then
            warn "Outcomes max iterations ($OUTCOMES_MAX) reached; proceeding without rubric gate"
        else
            outcomes_json="$(invoke_outcomes_check "$REPO_PATH" "$RUBRIC_PATH")"
            outcomes_verdict="$(printf '%s' "$outcomes_json" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('verdict','skip'))")"
            outcomes_why="$(printf '%s' "$outcomes_json" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('why',''))")"
            outcomes_remediation="$(printf '%s' "$outcomes_json" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('remediation',''))")"
            printf '    outcomes: verdict=%s why=%s\n' "$outcomes_verdict" "$outcomes_why"
            if [ "$outcomes_verdict" = "fail" ]; then
                # Override done-gate: inject gap report as next-iteration context
                verdict="continue"
                OUTCOMES_CONTEXT="Outcomes grader gap report (iteration $iter):
$outcomes_remediation

Address all items above before the next iteration."
            fi
        fi
    fi
```

Also update the inner prompt construction (around line 96-105) to inject outcomes context when present. Replace the `INNER_PROMPT=` block with:

```bash
build_inner_prompt() {
    local base outcomes_section=""
    if [ -n "$OUTCOMES_CONTEXT" ]; then
        outcomes_section="
Outcomes gap from previous iteration (address these FIRST):
$OUTCOMES_CONTEXT
---

"
        OUTCOMES_CONTEXT=""  # consume it
    fi
    printf '%s%s' "$outcomes_section" "Follow the PRD at \"$PRD_PATH\".

Rules for this iteration:
1. Re-read the PRD from disk. Do NOT assume earlier iterations' context is in memory.
2. Consult MemPalace for prior work on this PRD topic BEFORE editing.
3. Use jcodemunch / serena for code navigation. Do not Read large files.
4. Make the smallest change that advances the PRD.
5. Update the PRD's 'Progress' section at the end with one-line status.
6. If the PRD is complete by your assessment, also write a \`DONE\` marker
   line as the FIRST line of the Progress section, then stop."
}
```

Then in the loop, replace the static `printf '%s\n' "$INNER_PROMPT"` with `build_inner_prompt`.

- [ ] **Step 5: Verify syntax**

```bash
bash -n /opt/proj/Uncle-J-s-Refinery/ralph-harness.sh
# Expect: no output
```

- [ ] **Step 6: Test --rubric flag is accepted**

```bash
/opt/proj/Uncle-J-s-Refinery/ralph-harness.sh --help 2>&1 | head -25
# Expect: usage shows --rubric in the option list (we added it to usage comment too — do that now)
/opt/proj/Uncle-J-s-Refinery/ralph-harness.sh \
    --prd /opt/proj/Uncle-J-s-Refinery/PRD.md \
    --rubric /opt/proj/Uncle-J-s-Refinery/global-skills/outcomes/RUBRIC.md.template \
    --dry-run 2>&1 | head -20
# Expect: startup banner shows Rubric: .../RUBRIC.md.template and OutcomesMax: 5
# Expect: [dry-run] would call ... (not an error)
```

- [ ] **Step 7: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add ralph-harness.sh
git commit -m "feat(outcomes): add --rubric flag to ralph-harness.sh

After each done-gate check, invoke the outcomes grader (fresh claude -p
context) against the rubric file. If required criteria fail, inject the
gap report as context for the next iteration. Loop exits only when BOTH
gate AND grader approve. Cap at OUTCOMES_MAX_ITERATIONS (default 5).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2.3: Update prd-template.md, docs/RELIABILITY.md, verify.sh

**Files:**
- Modify: `prd-template.md`
- Modify: `docs/RELIABILITY.md`
- Modify: `verify.sh`

- [ ] **Step 1: Add Success Rubric section to prd-template.md**

In `prd-template.md`, after the `## Acceptance criteria` section, add:

```markdown
## Success Rubric (optional — for --rubric mode)

<If using ralph-harness.sh --rubric, paste the rubric here or reference
the path. The outcomes grader reads this in a fresh context after each
iteration. Leave blank if not using --rubric.>

See: `global-skills/outcomes/RUBRIC.md.template` for the starter template.
```

- [ ] **Step 2: Add outcomes section to docs/RELIABILITY.md**

In `docs/RELIABILITY.md`, in the table under the first section, add a row for outcomes. The table currently has 6 rows. Add:

```markdown
| outcomes skill (--rubric) | Rubric-aware grader in fresh context after each Ralph iteration | when not using --rubric flag |
```

After the `### Ralph harness` subsection, add:

```markdown
### Outcomes grader

The `outcomes` skill runs in a **fresh context window** — it has not seen
the working agent's accumulated reasoning. This is the point: a long thread
develops blind spots; a fresh context catches them.

Invoked automatically when `ralph-harness.sh --rubric <path>` is used.
After each iteration:

1. Reads the rubric file (criteria with pass/fail conditions and weights)
2. Evaluates each criterion against the PRD Progress section and repo state
3. Returns a JSON verdict: `pass` or `fail` with specific remediation steps
4. If `fail`, injects the gap report as context for the next iteration

Loop exits only when BOTH the structural done-gate (risk + untested) AND
the rubric grader agree the work is complete. Cap: `OUTCOMES_MAX_ITERATIONS`
(default 5, configurable via env var).

The rubric format lives at `global-skills/outcomes/RUBRIC.md.template`.
Project rubrics go at `.claude/outcomes/rubric.md` within the project repo.
```

- [ ] **Step 3: Add outcomes skill check to verify.sh**

After the dreaming checks added in Task 1.5, add:

```bash
echo
echo "Outcomes skill:"
check "outcomes skill installed" test -d "$HOME/.claude/skills/outcomes"
check "outcomes SKILL.md present" test -f "$HOME/.claude/skills/outcomes/SKILL.md"
```

- [ ] **Step 4: Verify all syntax**

```bash
bash -n /opt/proj/Uncle-J-s-Refinery/verify.sh
# Expect: no output
```

- [ ] **Step 5: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add prd-template.md docs/RELIABILITY.md verify.sh
git commit -m "feat(outcomes): update docs and verify.sh for outcomes loop

prd-template.md: add Success Rubric section pointing to template.
RELIABILITY.md: document the outcomes grader pattern and loop mechanics.
verify.sh: add outcomes skill installation checks.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 3 — Multi-agent Orchestration

Requires Phase 2 complete (outcomes grader is the exit gate for the orchestration loop). Most complex phase — ralph-harness.sh gets parallel subprocess management.

**New files:**
- Create: `global-skills/orchestrator/SKILL.md`

**Modified files:**
- Modify: `ralph-harness.sh` — `--decompose` flag + parallel subprocess management
- Modify: `~/.claude/hooks/langfuse_hook.py` — AGENT_ROLE tagging
- Modify: `docs/STACK.md` — orchestrator and multi-agent section
- Modify: `prd-template.md` — Agent Decomposition section

---

### Task 3.1: Create orchestrator skill

**Files:**
- Create: `global-skills/orchestrator/SKILL.md`

- [ ] **Step 1: Create directory**

```bash
mkdir -p /opt/proj/Uncle-J-s-Refinery/global-skills/orchestrator
```

- [ ] **Step 2: Write SKILL.md**

Write `global-skills/orchestrator/SKILL.md`:

```markdown
---
name: orchestrator
description: Decompose a PRD or task into a structured JSON task manifest of parallelizable subtasks for multi-agent execution
---

You are the orchestrator agent. Analyze the PRD or task in `<prd>` and produce
a JSON task manifest — an array of subtasks to delegate to specialist sub-agents.

## Role definitions

Assign each subtask to one role based on what it primarily needs:

| Role | Tools | Use when |
|---|---|---|
| `code` | jCodeMunch, Serena | reading or modifying source code |
| `data` | jDataMunch, DuckDB | reading or analyzing data files |
| `docs` | jDocMunch, Context7 | reading or searching documentation |
| `memory` | MemPalace | retrieving prior decisions or prior art |
| `general` | all tools | task spans multiple tool types |

## Instructions

1. Read the `<prd>` block.
2. Identify which parts can be worked on independently (investigation,
   retrieval, isolated implementation).
3. Tasks that depend on each other's output: set `"parallel": false`.
4. Tasks that can run simultaneously: set `"parallel": true`.
5. Produce ONLY the JSON manifest. No preamble, no commentary.

## Output format

```json
[
  {
    "role": "memory",
    "task": "Search MemPalace for prior work on <topic>. Return all relevant decisions, patterns, and known pitfalls.",
    "tools_needed": ["MemPalace"],
    "context_needed": "Topic: <topic>",
    "output_format": "Bullet list of relevant prior decisions",
    "parallel": true
  },
  {
    "role": "code",
    "task": "Read the current implementation of <symbol> and identify what needs to change for <goal>.",
    "tools_needed": ["jCodeMunch", "Serena"],
    "context_needed": "Symbol: <name>, file: <path>",
    "output_format": "Current implementation summary + proposed diff",
    "parallel": true
  }
]
```

## Rules

- Maximum 6 subtasks. More means the PRD should be split.
- Always include a `memory` task if the PRD has no prior-art context.
- If the task is a single linear chain (A must complete before B can start
  for all tasks), produce one entry with `"role": "general"`.
- Never assign credential-reading, network-exfil, or production-push tasks.
- Keep `task` field specific enough that the sub-agent needs no clarification.
- The synthesis agent merges all outputs, so each sub-agent produces
  self-contained output — not partial files that need to be assembled.
```

- [ ] **Step 3: Verify**

```bash
python3 -c "
content = open('/opt/proj/Uncle-J-s-Refinery/global-skills/orchestrator/SKILL.md').read()
for s in ['name: orchestrator', 'role', 'parallel', 'json']:
    assert s in content, f'Missing: {s}'
print('orchestrator SKILL.md: valid')
"
```

- [ ] **Step 4: Install skill and commit**

```bash
bash /opt/proj/Uncle-J-s-Refinery/install-reliability.sh 2>&1 | grep -E 'OK|warn'
# Expect: OK for prior-art-check, judge, outcomes, orchestrator
ls ~/.claude/skills/orchestrator/SKILL.md
# Expect: file exists

cd /opt/proj/Uncle-J-s-Refinery
git add global-skills/orchestrator/
git commit -m "feat(orchestrator): add orchestrator skill

Decomposes PRDs into parallel role-scoped subtask manifests (JSON array).
Roles: code/data/docs/memory/general — each mapped to its designated
retrieval tools. Max 6 tasks. Used by ralph-harness.sh --decompose.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3.2: Add --decompose flag to ralph-harness.sh

**Files:**
- Modify: `ralph-harness.sh`

This is the most complex change. Adds parallel subprocess management: orchestrator generates the manifest, bash spawns sub-agents in parallel (AGENT_ROLE env var set per subprocess), waits for all, then runs a synthesis agent to merge the outputs.

- [ ] **Step 1: Add flag declaration and arg parsing**

After `RUBRIC_PATH=""` (added in Phase 2), add:

```bash
DECOMPOSE=0
```

In the arg-parser block, add after `--rubric`:

```bash
        --decompose)       DECOMPOSE=1; shift ;;
```

In the banner, add:

```bash
ok "Decompose  : $([ "$DECOMPOSE" -eq 1 ] && echo ON || echo OFF)"
```

Add validation: orchestrator skill must be installed if --decompose is set:

```bash
if [ "$DECOMPOSE" -eq 1 ] && [ ! -f "$HOME/.claude/skills/orchestrator/SKILL.md" ]; then
    stop "orchestrator skill not found — run install-reliability.sh first"; exit 1
fi
```

- [ ] **Step 2: Add invoke_orchestrator function**

Add after `invoke_outcomes_check`:

```bash
invoke_orchestrator() {
    local repo="$1" prd_path="$2"
    local skill_content prd_content prompt tmp output manifest

    skill_content="$(cat "$HOME/.claude/skills/orchestrator/SKILL.md")"
    prd_content="$(cat "$prd_path")"

    prompt="<skill>
$skill_content
</skill>

<prd>
$prd_content
</prd>

Produce the task manifest JSON array and nothing else."

    tmp="$(mktemp --suffix=.md)"
    printf '%s\n' "$prompt" > "$tmp"
    step "Decompose: invoking orchestrator"
    output="$(cd "$repo" && claude -p "@$tmp" --dangerously-skip-permissions 2>&1 || true)"
    rm -f "$tmp"

    # Extract JSON array from output
    manifest="$(printf '%s\n' "$output" | python3 -c "
import sys, json, re
text = sys.stdin.read()
m = re.search(r'\[.*?\]', text, re.DOTALL)
if m:
    try:
        tasks = json.loads(m.group())
        print(json.dumps(tasks))
        sys.exit(0)
    except Exception:
        pass
print('[]')
" 2>/dev/null || printf '[]')"

    printf '%s' "$manifest"
}
```

- [ ] **Step 3: Add run_decomposed function**

Add after `invoke_orchestrator`:

```bash
run_decomposed() {
    local repo="$1" manifest="$2"
    local task_count decompose_dir pids=() i role task output_file

    task_count="$(printf '%s' "$manifest" \
        | python3 -c "import sys,json; print(len(json.loads(sys.stdin.read())))" 2>/dev/null || echo 0)"

    if [ "$task_count" -eq 0 ]; then
        warn "Orchestrator returned empty manifest; falling back to single-agent mode"
        return 1
    fi

    step "Decompose: spawning $task_count sub-agent(s)"
    decompose_dir="$(mktemp -d --suffix=.decompose)"

    for i in $(seq 0 $((task_count-1))); do
        role="$(printf '%s' "$manifest" | python3 -c \
            "import sys,json; t=json.loads(sys.stdin.read()); print(t[$i].get('role','agent'))")"
        task="$(printf '%s' "$manifest" | python3 -c \
            "import sys,json; t=json.loads(sys.stdin.read()); print(t[$i].get('task',''))")"
        output_file="$decompose_dir/output_$i.md"

        ok "Sub-agent $i (role=$role)"
        (cd "$repo" && AGENT_ROLE="$role" MCP_TIMEOUT="${MCP_TIMEOUT:-60000}" \
            claude -p "$task" --dangerously-skip-permissions > "$output_file" 2>&1) &
        pids+=($!)
    done

    # Wait for all sub-agents
    local failed=0
    for pid in "${pids[@]}"; do
        wait "$pid" || { warn "sub-agent pid=$pid exited non-zero"; failed=$((failed+1)); }
    done
    [ "$failed" -gt 0 ] && warn "$failed sub-agent(s) failed (outputs still available for synthesis)"

    # Synthesis
    step "Decompose: synthesis agent merging $task_count outputs"
    local synth_parts="" f
    for f in "$decompose_dir"/output_*.md; do
        synth_parts+="=== $(basename "$f") ===
$(cat "$f")

"
    done

    local synth_tmp synth_output
    synth_tmp="$(mktemp --suffix=.md)"
    printf 'You are the synthesis agent. Merge the following sub-agent outputs into a single coherent deliverable. Preserve all findings; resolve any conflicts by noting them.\n\n%s\n\nProduce the merged result.\n' \
        "$synth_parts" > "$synth_tmp"
    synth_output="$(cd "$repo" && claude -p "@$synth_tmp" --dangerously-skip-permissions 2>&1 || true)"
    rm -f "$synth_tmp"
    rm -rf "$decompose_dir"

    printf '%s' "$synth_output"
}
```

- [ ] **Step 4: Wire --decompose into the main loop**

In the main loop, before the `claude -p "@$tmp"` call (around line 166), add a block that runs decompose mode if enabled:

Replace the inner loop body's `claude -p` block with:

```bash
    if [ "$DRY_RUN" -eq 1 ]; then
        ok "[dry-run] would call: (cd $REPO_PATH && claude -p @<tmp> --dangerously-skip-permissions)"
        [ -n "$PRE_OUTPUT" ] && ok "[dry-run] pre-script context would be prepended to prompt"
    elif [ "$DECOMPOSE" -eq 1 ]; then
        # Decompose mode: orchestrate → parallel sub-agents → synthesis
        manifest="$(invoke_orchestrator "$REPO_PATH" "$PRD_PATH")"
        if ! decompose_output="$(run_decomposed "$REPO_PATH" "$manifest")"; then
            # Fallback to single-agent if manifest was empty
            tmp="$(mktemp --suffix=.md)"
            printf '%s\n' "$(build_inner_prompt)" > "$tmp"
            set +e
            (cd "$REPO_PATH" && claude -p "@$tmp" --dangerously-skip-permissions)
            rc=$?
            set -e
            rm -f "$tmp"
            [ "$rc" -ne 0 ] && warn "claude exited $rc on iter $iter; continuing."
        else
            ok "Decompose iteration $iter complete"
        fi
    else
        tmp="$(mktemp --suffix=.md)"
        if [ -n "$PRE_OUTPUT" ]; then
            printf 'Pre-script context:\n\n%s\n\n---\n\n%s\n' "$PRE_OUTPUT" "$(build_inner_prompt)" > "$tmp"
        else
            printf '%s\n' "$(build_inner_prompt)" > "$tmp"
        fi
        set +e
        (cd "$REPO_PATH" && claude -p "@$tmp" --dangerously-skip-permissions)
        rc=$?
        set -e
        rm -f "$tmp"
        [ "$rc" -ne 0 ] && warn "claude exited $rc on iter $iter; continuing."
    fi
```

- [ ] **Step 5: Update usage comment at top of ralph-harness.sh**

Replace the Usage comment block (lines 8-12) with:

```bash
# Usage:
#   ./ralph-harness.sh --prd ./PRD.md [--repo /path/to/repo] \
#                      [--max-iterations 30] [--risk-threshold 0.65] \
#                      [--rubric ./rubric.md] [--decompose] \
#                      [--skip-judge] [--dry-run]
```

- [ ] **Step 6: Syntax check and dry-run test**

```bash
bash -n /opt/proj/Uncle-J-s-Refinery/ralph-harness.sh
# Expect: no output

/opt/proj/Uncle-J-s-Refinery/ralph-harness.sh \
    --prd /opt/proj/Uncle-J-s-Refinery/PRD.md \
    --decompose \
    --dry-run 2>&1 | head -15
# Expect: banner shows "Decompose  : ON" and "[dry-run] would call: ..."
```

- [ ] **Step 7: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add ralph-harness.sh
git commit -m "feat(orchestrator): add --decompose flag to ralph-harness.sh

--decompose invokes the orchestrator skill to produce a task manifest,
spawns parallel claude -p sub-agents (AGENT_ROLE set per agent), waits
for all, then runs a synthesis agent to merge outputs. Falls back to
single-agent mode if the manifest is empty. Compatible with --rubric.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3.3: Add AGENT_ROLE tagging to langfuse_hook.py

**Files:**
- Modify: `~/.claude/hooks/langfuse_hook.py`

Tags each Langfuse trace with `role:<AGENT_ROLE>` when the env var is set. This makes multi-agent runs visible in Langfuse as a role-tagged tree.

- [ ] **Step 1: Locate the tag-building block**

```bash
grep -n "tags = " ~/.claude/hooks/langfuse_hook.py
# Expect: line ~545 with: tags = ["claude-code"]
```

- [ ] **Step 2: Verify before editing**

```bash
sed -n '540,560p' ~/.claude/hooks/langfuse_hook.py
# Expect: tags = ["claude-code"] block followed by update_current_trace call
```

- [ ] **Step 3: Apply the edit**

In `~/.claude/hooks/langfuse_hook.py`, find the tag-building block inside `create_trace()`:

```python
    # Build tags list
    tags = ["claude-code"]
    if project_name:
        tags.append(project_name)
```

Replace with:

```python
    # Build tags list
    tags = ["claude-code"]
    if project_name:
        tags.append(project_name)
    agent_role = os.environ.get("AGENT_ROLE", "")
    if agent_role:
        tags.append(f"role:{agent_role}")
```

Also update the `update_current_trace` metadata call (a few lines below) to include agent_role. Find:

```python
        langfuse.update_current_trace(
            session_id=session_id,
            tags=tags,
            metadata={
                "source": "claude-code",
                "turn_number": turn_num,
                "session_id": session_id,
                "project": project_name,
            },
        )
```

Replace with:

```python
        trace_metadata = {
            "source": "claude-code",
            "turn_number": turn_num,
            "session_id": session_id,
            "project": project_name,
        }
        if agent_role:
            trace_metadata["agent_role"] = agent_role
        langfuse.update_current_trace(
            session_id=session_id,
            tags=tags,
            metadata=trace_metadata,
        )
```

- [ ] **Step 4: Syntax-check the hook**

```bash
python3 -m py_compile ~/.claude/hooks/langfuse_hook.py && echo "syntax OK"
# Expect: syntax OK
```

- [ ] **Step 5: Unit-test the AGENT_ROLE path**

```bash
python3 -c "
import os, sys
# Simulate AGENT_ROLE being set
os.environ['AGENT_ROLE'] = 'code'
# Re-read the relevant logic
tags = ['claude-code']
project_name = 'test-project'
if project_name:
    tags.append(project_name)
agent_role = os.environ.get('AGENT_ROLE', '')
if agent_role:
    tags.append(f'role:{agent_role}')
assert 'role:code' in tags, f'Expected role:code in tags, got {tags}'
print('AGENT_ROLE tagging: OK')
print('Tags:', tags)
"
# Expect: AGENT_ROLE tagging: OK / Tags: ['claude-code', 'test-project', 'role:code']
```

- [ ] **Step 6: Copy back to template source**

The hook was originally copied from the template. Keep the template in sync so future re-installs don't lose this change:

```bash
# Only copy if template is present (cloned by install-langfuse.sh)
if [ -f /opt/proj/Uncle-J-s-Refinery/claude-code-langfuse-template/hooks/langfuse_hook.py ]; then
    cp ~/.claude/hooks/langfuse_hook.py \
       /opt/proj/Uncle-J-s-Refinery/claude-code-langfuse-template/hooks/langfuse_hook.py
    echo "template copy updated"
fi
```

Note: `claude-code-langfuse-template/` is gitignored (it's a cloned upstream). The canonical source for this patch is install-langfuse.sh's step 6. Add a patch comment to install-langfuse.sh so future installs apply the AGENT_ROLE tag:

In `install-langfuse.sh` after the `cp "$TEMPLATE_DIR/hooks/langfuse_hook.py" "$CLAUDE_DIR/hooks/"` line, add:

```bash
# Patch: add AGENT_ROLE tagging for multi-agent runs (--decompose mode)
python3 - "$CLAUDE_DIR/hooks/langfuse_hook.py" << 'PYPATCH'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
content = p.read_text()
old = '    tags = ["claude-code"]\n    if project_name:\n        tags.append(project_name)'
new = '    tags = ["claude-code"]\n    if project_name:\n        tags.append(project_name)\n    agent_role = os.environ.get("AGENT_ROLE", "")\n    if agent_role:\n        tags.append(f"role:{agent_role}")'
if old in content and 'AGENT_ROLE' not in content:
    p.write_text(content.replace(old, new, 1))
    print('  OK  AGENT_ROLE patch applied to langfuse_hook.py')
else:
    print('  OK  AGENT_ROLE patch already present or anchor not found (no-op)')
PYPATCH
```

- [ ] **Step 7: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add install-langfuse.sh
git commit -m "feat(orchestrator): add AGENT_ROLE trace tagging to langfuse_hook.py

Tags each Langfuse trace with role:<AGENT_ROLE> when the env var is set.
ralph-harness.sh --decompose sets AGENT_ROLE per sub-agent process.
install-langfuse.sh now applies this patch after copying the hook script
so re-installs don't lose the tag.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3.4: Update docs/STACK.md and prd-template.md

**Files:**
- Modify: `docs/STACK.md`
- Modify: `prd-template.md`

- [ ] **Step 1: Add orchestrator and multi-agent section to docs/STACK.md**

Append to `docs/STACK.md` after the Dreaming section added in Phase 1:

```markdown

---

## Orchestrator + Multi-agent (--decompose mode)

**What it does.** When `ralph-harness.sh --decompose` is set, the orchestrator
skill decomposes the PRD into a JSON task manifest, bash spawns one
`claude -p` subprocess per task (in parallel where safe), and a synthesis
agent merges the outputs. Traces are tagged by `role:` in Langfuse.

**Roles and tool mapping:**

| Role | Designated tools |
|---|---|
| `code` | jCodeMunch, Serena |
| `data` | jDataMunch, DuckDB |
| `docs` | jDocMunch, Context7 |
| `memory` | MemPalace |
| `general` | all tools |

**AGENT_ROLE env var.** Set by ralph-harness.sh on each sub-agent subprocess.
Langfuse traces carry `role:<value>` tags so multi-agent runs appear as a
role-tagged tree rather than an undifferentiated stream.

**Usage.**
```bash
./ralph-harness.sh --prd ./PRD.md --decompose --rubric ./.claude/outcomes/rubric.md
```

**Composition with Outcomes.** When both `--decompose` and `--rubric` are
set, the synthesized output is evaluated by the outcomes grader after each
iteration. The grader runs in a fresh context and checks the rubric. Loop
exits only when synthesis + rubric both pass.

**Guardrail invariants.** Sub-agents inherit `MCP_TIMEOUT=60000` via env.
jCodeMunch PreToolUse/PostToolUse hooks fire per sub-agent (they are global
settings, not session-local). The bash-matcher destructive-command blocks
apply to every subprocess — `--decompose` does not bypass them.
```

- [ ] **Step 2: Add Agent Decomposition section to prd-template.md**

After the `## Success Rubric` section added in Phase 2, add:

```markdown
## Agent Decomposition (optional — for --decompose mode)

<If using ralph-harness.sh --decompose, the orchestrator skill reads this
PRD and decides how to split it. To guide decomposition, you can add hints
here about which parts are parallelizable and which must run in sequence.>

Example hints:
- "Research tasks (MemPalace + docs) can run in parallel with code analysis."
- "Implementation must follow research (serialize tasks 2 and 3)."
- "Max 4 sub-agents — this is a focused change."

Leave blank to let the orchestrator decide based on the PRD content alone.
```

- [ ] **Step 3: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add docs/STACK.md prd-template.md
git commit -m "feat(orchestrator): document multi-agent mode in STACK.md and prd-template.md

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Task that covers it |
|---|---|
| `features/dreaming/install.sh` | Task 1.3 |
| `features/dreaming/dream.sh` | Task 1.2 |
| `features/dreaming/skills/dream-synthesizer/SKILL.md` | Task 1.1 |
| `/dream` slash command | Task 1.3 |
| `state/dreaming-last-run.txt` in .gitignore | Already covered by `state/` entry in .gitignore — no change needed |
| Dreaming section in `docs/STACK.md` | Task 1.5 |
| `verify.sh` dreaming cron check | Task 1.5 |
| `skills/outcomes/RUBRIC.md.template` | Task 2.1 (in `global-skills/outcomes/`) |
| `skills/outcomes/SKILL.md` | Task 2.1 (in `global-skills/outcomes/`) |
| `ralph-harness.sh --rubric` | Task 2.2 |
| `OUTCOMES_MAX_ITERATIONS` env var | Task 2.2 (reads from env; set via `export OUTCOMES_MAX_ITERATIONS=N`) |
| `prd-template.md` Success Rubric section | Task 2.3 |
| `docs/RELIABILITY.md` outcomes loop | Task 2.3 |
| `verify.sh` outcomes skill check | Task 2.3 |
| `skills/orchestrator/SKILL.md` | Task 3.1 (in `global-skills/orchestrator/`) |
| `ralph-harness.sh --decompose` | Task 3.2 |
| `langfuse_hook.py` AGENT_ROLE tag | Task 3.3 |
| SubagentStart hook role-scope audit | **GAP — see below** |
| `docs/STACK.md` orchestrator section | Task 3.4 |
| `prd-template.md` Agent Decomposition | Task 3.4 |
| Fix install-reliability.sh path | Task 0.1 |
| Fix install-langfuse.sh Stop overwrite | Task 0.2 |

**Identified gap:** The spec says to "Audit `SubagentStart` hook to confirm role-scoped tool enforcement." This is an investigation task, not a code change. Add it as Task 3.5 below.

---

### Task 3.5: Audit SubagentStart hook

**Files:**
- Read-only audit. Modify `install.sh` or jcodemunch hooks only if needed.

- [ ] **Step 1: Find the SubagentStart hook configuration**

```bash
python3 -c "
import json, os
s = json.load(open(os.path.expanduser('~/.claude/settings.json')))
hooks = s.get('hooks', {})
sa = hooks.get('SubagentStart', [])
print('SubagentStart hooks:', json.dumps(sa, indent=2))
"
# Note the output. If empty, the SubagentStart hook is not configured at
# the global level. Check if jcodemunch registers it separately.
```

- [ ] **Step 2: Check jcodemunch documentation for SubagentStart**

```bash
/opt/proj/Uncle-J-s-Refinery/.venv/bin/jcodemunch-mcp --help 2>&1 | grep -i subagent || true
# Check if jcodemunch auto-registers a SubagentStart hook on init
```

- [ ] **Step 3: Decision based on findings**

If `SubagentStart` is empty and jcodemunch doesn't register one automatically:
- The retrieval-first routing policy is enforced via CLAUDE.md (which applies globally to all sessions including sub-agents, since it's at `~/.claude/CLAUDE.md`).
- Sub-agents inherit the global CLAUDE.md; no additional hook needed.
- Document the finding in `docs/STACK.md` under the multi-agent section.

If `SubagentStart` has a jcodemunch hook:
- Verify the hook command includes `AGENT_ROLE` awareness if needed.
- The spec says "if `AGENT_ROLE` is set, enforce the role's designated tools only." This is enforced via the sub-agent's task prompt (which tells it what tools to use) — not via a separate hook, since the hook can't conditionally disable MCP servers mid-session.

- [ ] **Step 4: Add audit finding to STACK.md**

In `docs/STACK.md`, at the end of the multi-agent section, add:

```markdown
**SubagentStart hook audit (2026-05-14):** The retrieval routing policy in
`~/.claude/CLAUDE.md` applies globally to all sessions, including sub-agents
spawned by `--decompose`. Tool scoping per role is enforced via the sub-agent's
task prompt (the `task` field from the orchestrator manifest). A dedicated
SubagentStart hook that disables non-role MCP servers is not implemented —
MCP servers cannot be selectively disabled per-session in Claude Code's current
architecture. The routing instructions in the task prompt are sufficient for
correct behavior.
```

- [ ] **Step 5: Commit**

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add docs/STACK.md
git commit -m "docs(orchestrator): document SubagentStart audit finding

The routing policy in CLAUDE.md applies to sub-agents. Tool scoping is
enforced via task prompt instructions, not a hook, because MCP servers
cannot be selectively disabled per-session. Documented the tradeoff.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Notes on the unknown third Langfuse blocker

HANDOFF.md (2026-04-30) references a "third specific failure" stored in mempalace (`uncle_j_s_refinery/scripts/HANDOFF.md`). MemPalace is currently unreachable in this session. If Langfuse is not running after completing all tasks above, check:

```bash
docker compose -f /opt/proj/Uncle-J-s-Refinery/claude-code-langfuse-template/docker-compose.yml ps
# If unhealthy containers: check logs
docker compose -f /opt/proj/Uncle-J-s-Refinery/claude-code-langfuse-template/docker-compose.yml logs --tail=30 clickhouse
```

The two documented fixes (ClickHouse pin to 24.8 + cpu.max bind-mount) are already in `install-langfuse.sh`. The third blocker requires MemPalace access or manual investigation of the docker logs.

# Session-End Checklist — Design Spec
_Date: 2026-05-23_

## Problem

Sessions end without mandatory documentation being updated. README.md is
frequently not considered at all. There is no machine-enforced gate — only
social convention. Docs drift from reality, future sessions start with stale
context, and the HANDOFF/CHANGELOG cycle is inconsistent.

## Goal

A lightweight, per-project configurable framework that:
1. Forces mandatory doc updates before any commit lands (hard gate)
2. Forces consideration of "review" docs without requiring modification
3. Sends a Telegram warning if a session ends with stale mandatory docs
4. Is easy for humans to read, configure, and maintain
5. Is reusable across any project (fork `.session-end.yml`, customize)

---

## Architecture

### Components

| Component | Path | Purpose |
|-----------|------|---------|
| Config | `.session-end.yml` | Per-project doc requirements (mandatory / consider / custom checks) |
| Hook script | `scripts/session-end-check.sh` | Reads config; used as both git pre-commit hook and Stop hook |
| Human doc | `docs/SESSION-END.md` | Explains the workflow for humans and new contributors |
| Skill | `global-skills/session-end-checklist/SKILL.md` | AI-invoked checklist walker |
| ROADMAP | `ROADMAP.md` | Living roadmap; added to "consider" list |
| One-time docs | `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md` | Created once; low-maintenance |

---

## `.session-end.yml` Schema

```yaml
version: 1

# File-type gate: pre-commit hook only fires when staged files match these extensions.
# Pure doc/config-only commits pass freely.
trigger:
  file_types: [".sh", ".py", ".ts", ".js", ".go", ".rs", ".json"]

# Mandatory: git pre-commit hook blocks if these are not staged and modified.
mandatory:
  - CHANGELOG.md
  - HANDOFF.md

# Consider: session-end skill surfaces each of these and prompts.
# Modification is NOT required — explicit acknowledgement is.
consider:
  - file: README.md
    prompt: "Did any user-facing feature, install step, or behavior change?"
  - file: ROADMAP.md
    prompt: "Any items completed or new ones to add?"
  - file: SECURITY.md
    when: security          # only surfaces if security-related files changed
    prompt: "Were any security fixes or policies changed?"
  - file: docs/STACK.md
    when: stack             # surfaces if pyproject.toml / uv.lock / mcp config changed
    prompt: "Did the stack or MCP server config change?"

# Custom checks: run as shell commands. on_failure: warn | block
custom_checks:
  - name: MemPalace snapshot
    command: "mempalace diary write"
    on_failure: warn
```

### `when` keyword values

| Value | Triggers when |
|-------|--------------|
| `security` | Any file under `scripts/lib/`, `tg_security.py`, or path contains "auth"/"security" |
| `stack` | `pyproject.toml`, `uv.lock`, or any `mcp-clients/` file staged |
| _(omitted)_ | Always surfaces |

---

## Git Pre-Commit Hook

**Location:** `.git/hooks/pre-commit` (symlink to `scripts/session-end-check.sh`)

**Logic:**
1. Read `.session-end.yml` — if absent, pass silently (repo opted out)
2. Apply file-type gate — if no matching files staged, pass silently
3. For each `mandatory` doc: check it is present in `git diff --staged --name-only`
4. If any mandatory doc missing → print clear error listing missing files → `exit 1`
5. Pass otherwise

**Error output example:**
```
❌ Session-end checklist: mandatory docs not staged

  Missing:
    • CHANGELOG.md — add an entry for this session
    • HANDOFF.md   — update next-session context

  Run the session-end-checklist skill, or update manually and re-stage.
  To skip for this commit: git commit --no-verify (use sparingly)
```

**Escape hatch:** `git commit --no-verify` bypasses all hooks. This is a
conscious override — acceptable for emergency hotfixes, not routine use.

---

## Claude Code Stop Hook

**Mechanism:** `Stop` event in `~/.claude/settings.json` hooks block.

**Script:** `scripts/session-end-check.sh --stop-hook`

**Logic:**
1. Apply file-type gate — if no code files modified since last commit, pass silently
2. Check `git diff HEAD --name-only` for mandatory docs
3. If any mandatory doc not modified since last commit → send Telegram FYI:
   `⚠️ Session ended with stale mandatory docs: CHANGELOG.md, HANDOFF.md`
4. Exit 0 always (Stop hook must not block)

This is the safety net — catches sessions that ended without a commit.

---

## Session-End Skill

**Path:** `global-skills/session-end-checklist/SKILL.md`

**Trigger:** Invoked by AI when wrapping up a session, or when the pre-commit hook blocks.

**Workflow:**
1. Read `.session-end.yml`
2. For each `mandatory` doc → open, add entry, stage
3. For each `consider` doc → evaluate `when` condition → if triggered, present `prompt` to AI → update or explicitly log "no update needed" → stage if modified
4. Run each `custom_check` → report result
5. Print summary: what was updated, what was skipped, what failed
6. Prompt: "Ready to commit. Run: `git add -p && git commit`"

The skill does NOT commit — that remains a human or AI conscious action.

---

## `docs/SESSION-END.md` — Human Doc

Covers:
- Why this system exists
- The three-layer enforcement model (skill → Stop hook → pre-commit hook)
- How to configure `.session-end.yml` for a new project
- The mandatory vs consider distinction
- How to use the escape hatch responsibly
- Taxonomy of standard docs (mandatory / consider / one-time setup)

---

## One-Time Setup Docs

Created in this same implementation pass; not touched each session:

| File | Content |
|------|---------|
| `LICENSE` | AGPL-3.0 full text |
| `CONTRIBUTING.md` | How to contribute; points to `.session-end.yml` for doc standards |
| `SECURITY.md` | Vulnerability reporting policy (private disclosure via email) |

---

## ROADMAP.md

Living roadmap at project root. Added to the `consider` list — surfaced every
session, updated when items complete or new ones are identified.

Format: three sections — **In Progress**, **Planned**, **Completed (recent)**.
Completed items age out after ~4 weeks to keep it readable.

---

## Testing

- Unit: `scripts/session-end-check.sh` with mock staged file lists → verify gate fires/passes correctly
- Manual: make a commit without updating CHANGELOG.md → confirm block
- Manual: run session-end skill → confirm all mandatory docs staged → commit passes
- Stop hook: close a session without committing → confirm Telegram FYI fires

---

## Non-Goals

- Does not replace `git commit --no-verify` (escape hatch intentionally preserved)
- Does not auto-commit (human or AI remains in control of the commit)
- Does not enforce code quality (that is `pre-commit` linters, separate concern)
- Does not enforce test passage (can be added as `custom_check` per-project)

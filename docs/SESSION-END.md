# Session-End Documentation Standard

Every session that modifies code files must update mandatory documentation
before committing. This standard exists because docs drift silently — a
CHANGELOG entry takes 2 minutes and saves 20 minutes of archaeology next session.

---

## The Three-Layer Enforcement Model

```
Session ends
     │
     ▼
[1] session-end-checklist SKILL  ← AI-invoked; walks through all docs
     │ (if skipped)
     ▼
[2] Claude Code Stop hook        ← Telegram warning when session closes
     │                              with stale mandatory docs
     │ (if ignored)
     ▼
[3] git pre-commit hook          ← Hard block; commit refuses until docs staged
```

The skill is the happy path. The Stop hook catches a missed run. The git hook
is the final wall — it cannot be bypassed without an explicit `--no-verify`.

---

## Mandatory Docs (always)

These must appear in every commit that touches code files:

| Doc | What to update |
|-----|----------------|
| `CHANGELOG.md` | Add dated entry: what changed, what was added, what was fixed |
| `HANDOFF.md` | Update current state and next-session context |

---

## Consider Docs (check every session, update if needed)

These must be **consciously reviewed** each session. Update them if applicable;
explicitly skip them if not. Silent skips are the bug this standard fixes.

| Doc | Question to ask |
|-----|----------------|
| `README.md` | Did any install step, feature, command, or config key change? |
| `ROADMAP.md` | Were planned items completed? Are new items worth tracking? |
| `SECURITY.md` | Were any security fixes, policies, or auth flows changed? (`when: security`) |
| `docs/STACK.md` | Did the stack, MCP servers, or dependencies change? (`when: stack`) |

---

## File-Type Gate

The pre-commit hook only fires when staged files include code file types
(`.sh`, `.py`, `.ts`, `.js`, `.go`, `.rs`, `.json`). Pure documentation
commits — fixing a typo in README, editing this file — pass freely without
requiring mandatory doc updates.

---

## Configuring for Your Project

Every project that adopts this standard gets a `.session-end.yml` at its root:

```yaml
version: 1

trigger:
  file_types: [".sh", ".py", ".ts", ".json"]

mandatory:
  - CHANGELOG.md
  - HANDOFF.md

consider:
  - file: README.md
    prompt: "Did any user-facing feature, install step, or behavior change?"
  - file: ROADMAP.md
    prompt: "Any items completed or new ones to add?"

custom_checks:
  - name: memweave freshness
    command: "bash scripts/memweave/sync_memory.sh '' 15"
    on_failure: warn
```

(The memory snapshot is automatic — the Stop-hook + nightly `sync_memory.sh --all` cron ingest
the session into the memweave corpus; the optional check above just nudges an incremental sync.)

The `consider` list and `custom_checks` are fully customizable. The mandatory
list is the non-negotiable floor.

---

## Escape Hatch

```bash
git commit --no-verify
```

This bypasses all git hooks. It is intentionally available for emergencies
(production hotfix at 3am, revert commits, merge conflict resolution). It is
not for routine use. The Stop hook will still fire and send a Telegram warning.

---

## Installing in a New Project

1. Copy `.session-end.yml` from this repo and customize it
2. Symlink the hook script:
   ```bash
   ln -sfn /path/to/scripts/session-end-check.sh .git/hooks/pre-commit
   ```
3. Add the Stop hook to `~/.claude/settings.json`:
   ```json
   {
     "type": "command",
     "command": "bash /path/to/scripts/session-end-check.sh --stop-hook",
     "timeout": 10
   }
   ```
4. Copy `global-skills/session-end-checklist/SKILL.md` into your skills directory

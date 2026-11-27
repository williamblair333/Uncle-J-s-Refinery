# Session-End Documentation Standard

Update the required docs before you commit code changes.
A CHANGELOG entry takes 2 minutes and saves 20 minutes of digging
through Git history next session.

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

The skill is the normal path: it gives your assistant a checklist to follow. A
hook is a command that runs automatically when an event happens. If the skill is
skipped, the Stop hook warns you when the session ends with required docs out of
date. If that warning is ignored, the Git hook blocks any commit that is missing
the docs. Only an explicit `--no-verify` gets past it.

---

## Mandatory Docs (always)

Include updates to both files in every commit that touches code files (see File-Type Gate below).

| Doc | What to update |
|-----|----------------|
| `CHANGELOG.md` | Add a dated entry. Say what you changed, added, or fixed. |
| `HANDOFF.md` | Record where things stand and what the next session needs to know. |

---

## Consider Docs (check every session, update if needed)

Review each file below every session. Update it if something changed.
If it needs no update, say you're skipping it so others know you checked.

| Doc | Question to ask |
|-----|----------------|
| `README.md` | Did any install step, feature, command, or config key change? |
| `ROADMAP.md` | Were planned items completed? Are new items worth tracking? |
| `SECURITY.md` | Were any security fixes, policies, or auth flows changed? (`when: security`) |
| `docs/STACK.md` | Did the project's tools, dependencies, or MCP servers change? MCP servers give assistants access to tools or information. (`when: stack`) |

---

## File-Type Gate

The pre-commit hook checks for doc updates only if you've staged a file with one
of these extensions (`.sh`, `.py`, `.ts`, `.js`, `.go`, `.rs`, `.json`). Staged
files are the ones you've marked for the next commit. Commits that change only
documentation, such as fixing a typo in the README or editing this file, pass
without `CHANGELOG.md` or `HANDOFF.md` updates.

---

## Configuring for Your Project

Put a `.session-end.yml` in the project's top-level directory to adopt this standard.

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

Session memory is saved automatically. The Stop hook and the nightly
`sync_memory.sh --all` job add each session to memweave, the project's
searchable store of past sessions. The optional check above only asks for a
quick sync of recent changes.

Change the `consider` list and `custom_checks` freely to fit your project. The
`mandatory` list is the minimum: you can add to it but not remove from it.

---

## Escape Hatch

```bash
git commit --no-verify
```

This skips all Git hooks. Use it only in emergencies, such as a production fix
at 3am, a revert, or resolving a merge conflict. It is not for routine use. The
Stop hook still runs and sends a Telegram warning.

---

## Installing in a New Project

1. Copy `.session-end.yml` from this repo and customize it
2. Create a symbolic link so Git can find the hook script.
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

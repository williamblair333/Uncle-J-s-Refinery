---
name: session-end-checklist
description: Run the session-end documentation checklist — updates CHANGELOG, HANDOFF, and considers README/ROADMAP before committing. Invoke when wrapping up a session, or when the pre-commit hook blocks a commit.
---

## When to use

- When wrapping up a session (proactively, before attempting a commit)
- When `git commit` is blocked by the pre-commit hook with "mandatory docs not staged"
- When asked to "do the session-end checklist" or "wrap up docs"

## Process

Read `.session-end.yml` from the project root first. If absent, use the
defaults: mandatory = [CHANGELOG.md, HANDOFF.md], consider = [README.md, ROADMAP.md].

### Step 1 — CHANGELOG.md (mandatory)

Open CHANGELOG.md. Add a new entry under the appropriate date heading
(format: `## YYYY-MM-DD — <one-line session summary>`). Include:

- What was changed, added, or fixed — grouped by type (Added / Fixed / Changed)
- Script/file names so future sessions can grep for context
- Keep entries concise: one bullet per logical change, not per file edit

Stage: `git add CHANGELOG.md`

### Step 2 — HANDOFF.md (mandatory)

Open HANDOFF.md. Replace or update the "Current State" and "Next Session"
sections to reflect:

- What was completed this session
- What is in-progress or blocked
- The single most important thing the next session should know
- Any state files, pending flags, or environment quirks worth noting

Stage: `git add HANDOFF.md`

### Step 3 — README.md (consider)

Scan what changed this session. Ask: did any of the following change?
- Install steps or prerequisites
- Feature list or bot commands
- Configuration keys or environment variables
- Cron jobs, hooks, or scripts the user runs

If yes → update README.md and stage it.
If no → explicitly note "README checked — no update needed" and move on.
Do NOT skip this step silently.

### Step 4 — ROADMAP.md (consider)

Open ROADMAP.md. Ask:
- Were any "In Progress" or "Planned" items completed this session?
- Are there new items identified this session that should be tracked?

Move completed items to "Completed (recent)". Add new ones to "Planned".
Age out completed items older than ~4 weeks.

If no changes needed → note "ROADMAP checked — no update needed" and move on.

### Step 5 — Conditional docs

Check `.session-end.yml` `consider` list for `when:` conditions:

- `when: security` — surfaces if any `tg_security.py`, `scripts/lib/`, or auth-related file changed. If triggered, check SECURITY.md.
- `when: stack` — surfaces if `pyproject.toml`, `uv.lock`, or `mcp-clients/` changed. If triggered, check `docs/STACK.md`.

### Step 6 — Custom checks

Run each `custom_checks` entry from `.session-end.yml`:

```bash
mempalace diary write   # snapshot this session to MemPalace
```

If a check fails and `on_failure: warn`, log the failure and continue.
If `on_failure: block`, stop and report.

### Step 7 — Commit

Once all mandatory docs are staged and consider docs are addressed:

```bash
git status              # confirm staged files
git commit -m "..."     # commit with descriptive message
```

The pre-commit hook will now pass.

## Notes

- Never skip Step 3 (README) silently — the whole point is forced consideration.
- Custom checks run last so they capture the final state.
- If the pre-commit hook already blocked once, re-stage the updated docs and retry.

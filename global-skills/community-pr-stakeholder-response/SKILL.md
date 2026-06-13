---
name: community-pr-stakeholder-response
description: Use when tagged as a stakeholder on an open-source PR or issue comment, especially when the PR has evolved since your last review, involves architectural changes, or requests sign-off on a change touching shared dependencies or parallel work.
---

## When to use

When you're tagged on a community or upstream PR and need to draft a thoughtful response — especially when the PR has evolved since you last reviewed it, involves architectural changes, or touches work that parallels your own.

## Steps

1. **Prior art check** — search memweave for prior involvement: earlier review comments, related decisions, known concerns from past sessions. (`.venv-memweave/bin/python scripts/memweave/mw_search.py "<topic>" --k 5`)

2. **Fetch current PR state** — `gh pr view <number>` + `gh pr view <number> --comments` to get the full picture: title, description, latest comment, and any tags/mentions.

3. **Identify architectural significance** — ask:
   - What changed between the original PR and now?
   - Does the change shift responsibility between layers (e.g., model-discipline → hook-layer injection)?
   - Does any flag flip opt-in → opt-out at a future version? Flag it explicitly.
   - Does an `experimental` label affect documentation stability?

4. **Check your prior comments** — scroll `gh pr view --comments` for your earlier review points. Confirm they were addressed, and reference them if relevant.

5. **Draft the response** — structure:
   - Acknowledge the bump and shared context (if relevant)
   - Address each architectural change with a concrete observation
   - Flag opt-out defaults or stability concerns explicitly
   - Close with a specific next step (what you'll review once pushed, what you'd keep opt-in)

6. **Pre-mortem before posting** — invoke the `pre-mortem` skill before `gh pr comment` or any public post. A community comment is hard to walk back.

## Key signals that warrant careful analysis (not a quick LGTM)

- Opt-in → opt-out default flips at a future version
- `experimental` API used as the public surface in docs
- Architectural shift removes a prior constraint (e.g., "model must remember to search" → "hook injects automatically")
- Token cost or privacy implications for users who didn't opt into the new behavior

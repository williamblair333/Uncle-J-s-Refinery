---
name: gemini-auto-skill
description: Monitors Gemini CLI sessions for reusable workflows and drafts native Gemini skills.
---

# Gemini Auto-Skill

## Objective
Automatically identify repeatable patterns and specialized workflows demonstrated during a session and draft them as native Gemini CLI skills.

## Instructions
1.  **Monitor**: Throughout the session, look for multi-step procedures, complex command sequences, or specialized research patterns that would be useful to automate.
2.  **Evaluate**: At the end of a major task, evaluate if a new skill is warranted.
    - **YES**: If the workflow is generalizable and requires more than 3 steps.
    - **NO**: If the task was a one-off fix or routine maintenance.
3.  **Draft**: If a skill is warranted, use the `skill-creator` tool (or manually draft the files) to create a new skill in `.gemini/skills/<skill-name>/`.
    - Include a clear `description` to ensure the skill is auto-activated in future sessions.
    - Bundle any necessary helper scripts in the skill's `scripts/` directory.
4.  **Notify**: Inform the user that a new Gemini skill draft has been created and is ready for use.

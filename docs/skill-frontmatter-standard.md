# Skill Frontmatter Standard

Use this format for every Refinery skill. Frontmatter is the block at the
top of a skill file that tells the assistant what the skill does and what
it needs. The format comes from the hermes-agent SKILL.md convention
(NousResearch).

## Full template

```yaml
---
name: skill-name                        # required; matches directory name
description: One-liner shown in /skills listing and routing decisions.
version: 1.0.0                          # semver; bump on any behavior change
platforms: [linux, macos]              # omit if universal (all platforms)
category: security                      # see category list below
tags: [tag1, tag2]                      # free-form; used for search/discovery
prerequisites:
  commands: [git, gh]                   # required CLI tools
  env_vars: [TELEGRAM_BOT_TOKEN]        # required env vars (omit if none)
  skills: [pre-mortem]                  # skills that must run first or are depended on
related_skills: [blue-team, outcomes]  # loosely related (not hard deps); omit if none
---
```

## Required fields

| Field | Notes |
|---|---|
| `name` | Must match the directory name exactly |
| `description` | Write one sentence with no period. It appears in the `/skills` listing. |
| `version` | Use semantic versioning. Increase the middle number for behavior changes. Increase the last number for wording changes. |

## Optional fields

| Field | Notes |
|---|---|
| `platforms` | Leave this out if the skill works everywhere. Use `[linux]` for skills that rely on cron, systemd, or hooks. Cron schedules jobs. Systemd manages services. Hooks run when an event happens. |
| `category` | Omit only for uncategorized experiments |
| `tags` | At least 2–4 tags. Choose words someone would search for. |
| `prerequisites.commands` | List required command-line tools (git, gh, uv, jcodemunch). They must be on PATH, the list of directories your shell searches for commands. |
| `prerequisites.env_vars` | List the environment variables the skill reads. These are settings it gets from the process that runs it. Leave out the `[]` if the list is empty. |
| `prerequisites.skills` | Other skills that must run first in the same session |
| `related_skills` | Hints that point readers to related skills. Nothing enforces them. |

## Category list

| Category | What qualifies |
|---|---|
| `security` | pre-mortem, red-team, blue-team, adversarial-review, telegram-security-audit |
| `review` | smart-review, code-review, adversarial-review, per-task-review-cycle, validate-external-audit |
| `memory` | memweave skills, prior-art-check, post-audit-memory-capture |
| `git` | session-end-checklist, catch-up-pull, verify-pr-branch, readme-sync |
| `analysis` | deep-repo-analysis, competitive-analysis, eval skills |
| `infrastructure` | post-upgrade-mcp-integration, stack-not-at-head-remediation, install scripts |
| `utility` | terse-reply, token-economy-prompt-authoring, prior-art-check |

## Migration priority

The first skills to switch were the ones that run every session
(pre-mortem, smart-review, session-end-checklist, prior-art-check).
Switch the remaining 45+ skills as you edit them.

## Differences from hermes

- Put all fields at the top level without a `metadata.hermes.*` wrapper.
- Leave out `author` and `license` because these skills are internal to Refinery.
- Use `prerequisites.skills` to name the skills that must run before this one.
- Use Refinery's category names.

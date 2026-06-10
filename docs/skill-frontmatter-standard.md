# Skill Frontmatter Standard

Adapted from the hermes-agent SKILL.md convention (NousResearch).
All Refinery skills should conform to this spec.

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
| `description` | One sentence; no period; shown in `/skills` listing |
| `version` | Semver; bump minor on behavior changes, patch on wording |

## Optional fields

| Field | Notes |
|---|---|
| `platforms` | Omit = universal. Use `[linux]` for cron/systemd/hook skills |
| `category` | Omit only for uncategorized experiments |
| `tags` | At least 2–4; include the most likely search terms |
| `prerequisites.commands` | Tools that must be on PATH (git, gh, uv, jcodemunch) |
| `prerequisites.env_vars` | Env vars the skill reads; omit the `[]` if empty |
| `prerequisites.skills` | Other skills that must run first in the same session |
| `related_skills` | Navigation hints; not enforced |

## Category list

| Category | What qualifies |
|---|---|
| `security` | pre-mortem, red-team, blue-team, adversarial-review, telegram-security-audit |
| `review` | smart-review, code-review, adversarial-review, per-task-review-cycle, validate-external-audit |
| `memory` | All mempalace-* skills, prior-art-check, post-audit-mempalace-capture |
| `git` | session-end-checklist, catch-up-pull, verify-pr-branch, readme-sync |
| `analysis` | deep-repo-analysis, competitive-analysis, eval skills |
| `infrastructure` | post-upgrade-mcp-integration, stack-not-at-head-remediation, install scripts |
| `utility` | terse-reply, token-economy-prompt-authoring, prior-art-check |

## Migration priority

Skills that fire every session (pre-mortem, smart-review, session-end-checklist, prior-art-check)
were migrated first as the pilot. Remaining 45+ skills: migrate opportunistically when editing.

## Differences from hermes

- No `metadata.hermes.*` nesting — all fields are top-level
- No `author` or `license` (all Refinery-internal)
- Added `prerequisites.skills` — explicit skill dependency graph
- Categories are Refinery-specific (not hermes category names)

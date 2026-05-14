# Session Stats

Weekly efficiency reporter for Uncle J's Refinery. Queries Langfuse for the
past 7 days of Claude Code sessions and renders a markdown table grouped by
date and project.

## What it does

1. Reads Langfuse credentials from `~/.claude/settings.json` env block
2. Queries `/api/public/traces?limit=500&fromTimestamp=<7-days-ago>`
3. Groups traces by date + project; tallies traces, tool calls, and tokens
4. Flags any session exceeding 40k tokens as `⚠ high`
5. In `--cron` mode, writes output to:
   - `~/.claude/dreaming-output/stats-YYYY-MM-DD.md` (picked up by dreaming on next run)
   - `state/stats-weekly.md` (human reference)

## Prerequisites

- Langfuse running and recording traces (`install-langfuse.sh`)
- Stack venv present (`install.sh`)

## Install

```bash
bash features/session-stats/install.sh
```

Installs the `/stats` slash command and registers a Sunday 8 AM cron job.

## Manual trigger

```bash
# Print to stdout
bash features/session-stats/stats.sh

# Look back 14 days instead of 7
bash features/session-stats/stats.sh --days 14

# Write to dreaming-output + state/ (same as cron)
bash features/session-stats/stats.sh --cron

# Smoke test (no Langfuse call)
bash features/session-stats/stats.sh --dry-run

# Or from inside a Claude Code session:
/stats
```

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `STATS_CRON_SCHEDULE` | `0 8 * * 0` | Cron schedule (every Sunday 8 AM) |
| `DREAMING_OUTPUT_DIR` | `~/.claude/dreaming-output` | Where cron writes the dated report |

Set in `state/session-stats.env` (written by install.sh, gitignored).

## Uninstall

```bash
bash features/session-stats/install.sh --uninstall
```

Removes the cron entry. The `/stats` command stays installed. To fully remove:

```bash
rm ~/.claude/commands/stats.md
```

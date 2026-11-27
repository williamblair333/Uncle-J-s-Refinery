# Session Stats

Session Stats shows how much work Claude Code did across projects in the past 7 days. It reads session records from Langfuse and puts the totals in a Markdown table grouped by date and project.

## What it does

1. Reads Langfuse credentials from the environment settings in `~/.claude/settings.json`.
2. Queries `/api/public/traces?limit=500&fromTimestamp=<7-days-ago>`
3. Groups traces, or records of activity, by date and project. It counts traces, tool calls, and tokens, the chunks of text a model processes.
4. Marks sessions that use more than 40k tokens as `⚠ high`.
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

The installer adds the `/stats` command and schedules an automatic run for Sunday at 8 AM.

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

Set these values in `state/session-stats.env`. install.sh creates the file, and Git ignores it.

## Uninstall

```bash
bash features/session-stats/install.sh --uninstall
```

This removes the scheduled run. The `/stats` command stays installed. Use the following command to remove it too.

```bash
rm ~/.claude/commands/stats.md
```

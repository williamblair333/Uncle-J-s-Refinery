# Dreaming

Dreaming reviews past Claude Code sessions on a schedule. It saves recurring mistakes and steps that worked so future sessions can learn from them. The memweave memory store receives both, and `~/.claude/CLAUDE.md` receives the playbooks.

It's modelled on the Dreaming feature Anthropic announced at Code with Claude (May 7, 2026), but it's built separately. It uses traces, or records of what happened, that the Langfuse Stop hook already records, so nothing extra needs to be set up to collect them.

## What it does

1. Asks Langfuse for traces recorded since the last run.
2. Builds a prompt with the task, the tools used, and the outcome.
3. Invokes the `dream-synthesizer` skill via `claude -p`
4. Synthesizer returns `## Recurring Mistakes` and `## Proven Playbooks`
5. Saves the output to `~/.claude/dreaming-output/dream-YYYY-MM-DD.md`
6. The nightly `sync_memory.sh --all` run adds the output to the memweave memory store.
7. Adds proven playbooks to `~/.claude/CLAUDE.md` without duplicating them on a rerun.

## Prerequisites

- Langfuse running and traces being recorded (install-langfuse.sh)
- memweave store provisioned (`.venv-memweave` + `~/.uncle-j-memory`, via install.sh)
- Claude CLI on PATH

## Install

```bash
bash features/dreaming/install.sh
```

## Manual trigger

```bash
bash features/dreaming/dream.sh

# Or from inside a Claude Code session:
/dream
```

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `DREAMING_CRON_SCHEDULE` | `0 2 * * *` | Schedule for the automatic run (2 AM daily) |
| `DREAMING_ENABLED` | `1` | Set to `0` to skip cron without uninstalling |
| `DREAMING_OUTPUT_DIR` | `~/.claude/dreaming-output` | Where output files are written |

Set these values in `state/dreaming.env`. install.sh creates the file, and Git ignores it.

## Uninstall

```bash
bash features/dreaming/install.sh --uninstall
```

This removes the scheduled run. The skill and command stay installed. Use the following command to remove them too.

```bash
rm -rf ~/.claude/skills/dream-synthesizer ~/.claude/commands/dream.md
```

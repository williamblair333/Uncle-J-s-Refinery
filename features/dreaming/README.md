# Dreaming

Scheduled batch process that mines past Claude Code sessions and writes
playbooks and mistake patterns back to the memweave corpus and `~/.claude/CLAUDE.md`.

Inspired by Anthropic's Dreaming capability announced at Code with Claude
(May 7, 2026). The implementation uses the Langfuse Stop hook traces that
are already being recorded, so there is no additional instrumentation needed.

## What it does

1. Queries Langfuse REST API for traces since the last run
2. Formats traces into a structured prompt (task, tools used, outcome)
3. Invokes the `dream-synthesizer` skill via `claude -p`
4. Synthesizer returns `## Recurring Mistakes` and `## Proven Playbooks`
5. Output written to `~/.claude/dreaming-output/dream-YYYY-MM-DD.md`
6. The memweave corpus ingests the output (nightly `sync_memory.sh --all`)
7. Proven playbooks appended to `~/.claude/CLAUDE.md` (idempotent)

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
| `DREAMING_CRON_SCHEDULE` | `0 2 * * *` | Cron schedule (2 AM daily) |
| `DREAMING_ENABLED` | `1` | Set to `0` to skip cron without uninstalling |
| `DREAMING_OUTPUT_DIR` | `~/.claude/dreaming-output` | Where output files are written |

Set in `state/dreaming.env` (written by install.sh, gitignored).

## Uninstall

```bash
bash features/dreaming/install.sh --uninstall
```

Removes the cron entry. Skill and command stay installed. To fully remove:

```bash
rm -rf ~/.claude/skills/dream-synthesizer ~/.claude/commands/dream.md
```

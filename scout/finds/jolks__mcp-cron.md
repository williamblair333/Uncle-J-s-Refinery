# jolks/mcp-cron

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/jolks/mcp-cron
- Stars: 28 (gh, 2026-11-24)
- Licence: NOASSERTION
- Last commit: 2026-09-04
- Source: discovered · Scheduling and maintenance automation (covered)

MCP server for scheduling and running AI prompts, HTTP/webhook requests, and shell commands

## Take

Uncle J's scheduling is system cron plus catch-up scripts, with no way to list, add or change jobs and read their run results from inside a session.

A single Go binary that runs as an MCP server and schedules shell commands and AI prompts by cron expression, keeping tasks and results in local SQLite. It comes in as an ordinary MCP server, so Uncle J stays the runtime, and its AI tasks accept a custom OpenAI-compatible base URL, so they could point at the local Ollama or llama-server instead of a hosted API. Build it from source or pin the binary rather than using the npx route, which fetches at launch.

Risk: It overlaps the existing cron and cron_catchup setup, lets an agent schedule arbitrary shell commands, and in stdio mode jobs only fire while the client session is alive, so it would need to run as a standing HTTP service.

Scores: tokens 3/5, accuracy 2/5, creativity 2/5, offline 4/5

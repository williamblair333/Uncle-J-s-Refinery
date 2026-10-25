# mdombrov-33/vex-mcp

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/mdombrov-33/vex-mcp
- Stars: 2 (gh, 2026-10-25)
- Licence: MIT
- Last commit: 2026-06-20
- Source: discovered · Guardrails and prompt-injection defense (thin)

MCP proxy that blocks tool poisoning, rug pulls, and excessive agency in real time

## Take

Nothing in Uncle J checks MCP traffic itself: there's no defence against poisoned tool descriptions, against third-party servers (serena, context7, duckdb launched via uvx/npx) changing their tool definitions after approval, or against a tool call that does too much.

Vex is a transparent stdio MCP proxy. You add it to a server's spawn command in claude-code-mcp.json, and it checks every JSON-RPC message for tool poisoning, rug pulls and calls outside an allowlist. It decides allow/flag/block and writes every decision to an audit log. It runs as a separate wrapper, so Uncle J stays the runtime, it works fully offline, and removing it is a one-line revert per server. That beats mcp-bastion, which needs Node and adds control tools that cost context, and pytector, which needs transformer models and doesn't touch MCP traffic.

Risk: Uncle J's own tool descriptions are long and full of instructions, so a poisoning detector could flag or block legitimate jcodemunch/jdocmunch tools. That would look like an empty or degraded result, so run it in flag-only mode against the local servers first.

Scores: tokens 4/5, accuracy 3/5, creativity 2/5, offline 5/5

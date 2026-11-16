# Gowthaman90/mcp-bastion

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/Gowthaman90/mcp-bastion
- Stars: 7 (gh, 2026-11-16)
- Licence: Apache-2.0
- Last commit: 2026-11-13
- Source: discovered · Guardrails and prompt-injection defense (thin)

Reliability & security proxy for the Model Context Protocol (MCP). Self-healing connections, runtime tool-poisoning/shadowing defense, and NIST AI RMF + OWASP LLM Top-10 audit trails for any MCP server. Works with Claude, Cursor, Cline, Windsurf.

## Take

Uncle J doesn't check MCP traffic while it runs: nothing catches poisoned or shadowed tool descriptions, a tool whose schema changes after it was trusted, or a server that dies mid-session across its eight-plus servers.

It's a client-agnostic proxy that sits between Claude Code and each MCP server. It defends against tool poisoning and shadowing, restarts crashed servers, and keeps an audit trail; removing it is a one-line config revert. It arrives as an MCP-layer wrapper, so Uncle J stays the runtime and the existing servers run unchanged. It needs Node, which context7 already depends on, and TypeScript only as a build tool. Of this batch it's the most mature and broadest fit: mcp-shield is a lighter Python alternative focused on scanning, mcp-fortress makes big claims with little behind them, and the other two are standalone platforms or apps.

Risk: Every MCP call would pass through one third-party proxy, a new single point of failure that adds latency, and its security coverage figures come from a benchmark written by the same author.

Scores: tokens 2/5, accuracy 3/5, creativity 2/5, offline 4/5

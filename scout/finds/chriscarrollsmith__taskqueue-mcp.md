# chriscarrollsmith/taskqueue-mcp

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/chriscarrollsmith/taskqueue-mcp
- Stars: 71 (gh, 2026-11-07)
- Licence: MIT
- Last commit: 2025-04-12
- Source: discovered · Multi-agent orchestration (thin)

MCP tool for exposing a structured task queue to guide AI agent workflows. Great for taming an over-enthusiastic Claude. 

## Take

The orchestrator skill writes a task manifest, but nothing in the listed stack durably tracks that plan or enforces its status transitions and approval gates across sessions.

A small MCP server that holds projects and tasks in a state machine:  requires , approved tasks lock, and a project can't be approved until every task is done and approved. It suits Uncle J because it adds a mechanical check on "done" as a plain MCP server, leaving the runtime alone, while the other candidates are full orchestrators or overlap memweave. Its checks only prove that a task was recorded and approved, so  still has to confirm the work.

Risk: It may add little beyond Claude Code's own task tracking, while its roughly 14 tool schemas cost tokens, it needs Node, and approval steps could slow autonomous runs.

Scores: tokens 2/5, accuracy 3/5, creativity 1/5, offline 4/5

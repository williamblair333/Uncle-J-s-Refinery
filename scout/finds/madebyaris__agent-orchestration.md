# madebyaris/agent-orchestration

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/madebyaris/agent-orchestration
- Stars: 21 (gh, 2026-10-27)
- Licence: MIT
- Last commit: 2026-04-05
- Source: discovered · Multi-agent orchestration (thin)

Agent Orchestration: MCP server enabling multi-agent collaboration with shared memory, task queue, resource locks, Cursor rules, and AGENTS.md workflows.

## Take

Uncle J's orchestrator skill splits a task into a manifest of parallel subtasks, but nothing at runtime stops parallel agents from claiming the same task or editing the same file.

It's a small MCP server that gives agents a shared task queue with dependencies, resource locks, and a list of which agents are working on the project, all kept in the project directory. That covers the step after the orchestrator manifest: agents claim tasks in turn and lock files, without Uncle J handing control to an outside framework the way aqm and Network-AI would. Continuum mostly repeats memweave and installs itself through a CLAUDE.md autostart. taskqueue-mcp is a single-agent checklist that the existing skills mostly cover.

Risk: Its shared-memory layer and its automatic writes to activeContext.md and AGENTS.md overlap with memweave and HANDOFF, so it would need to run with context sync off and only its queue and lock tools in use.

Scores: tokens 3/5, accuracy 4/5, creativity 2/5, offline 5/5

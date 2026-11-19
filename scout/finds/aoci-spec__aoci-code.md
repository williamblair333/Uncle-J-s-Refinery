# aoci-spec/aoci-code

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/aoci-spec/aoci-code
- Stars: 2466 (gh, 2026-11-19)
- Licence: NOASSERTION
- Last commit: 2026-11-19
- Source: discovered · Agent memory (covered)

A persistent, Git-versioned map of your whole codebase and database schema that coding agents read before they touch anything. Local-first MCP server + CLI in Go: a governed repository index of code knowledge that gives Claude Code, Codex, Cursor, and opencode long-term context, memory, and code intelligence.

## Take

Uncle J has no durable map of each file's purpose and the rules it must not break, stored and versioned in the repo itself; jcodemunch indexes symbols but doesn't capture intent or invariants.

It's a local Go MCP server and CLI that keeps one line per file, written by the agent. Each line records the file's job, what to read alongside it, what callers depend on, and safety invariants. The index is committed to Git, so it survives across sessions, machines and agents, and it reports which entries are stale after code changes. That makes it a cheap orientation layer to run before jcodemunch on Bill's larger repos, and it needs no hosted model.

Risk: The entries are model-written prose, so a wrong or stale invariant would be read as truth and hurt accuracy, and on very large repos the full index costs a lot of tokens to read.

Scores: tokens 4/5, accuracy 3/5, creativity 3/5, offline 5/5

# optave/ops-codegraph-tool

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/optave/ops-codegraph-tool
- Stars: 103 (gh, 2026-11-20)
- Licence: Apache-2.0
- Last commit: 2026-11-13
- Source: discovered · Code intelligence (covered)

Code intelligence CLI — function-level dependency graph across 34 languages, 34-tool MCP server for AI agents, complexity metrics, architecture boundary enforcement, CI quality gates, git diff impact with co-change analysis, hybrid semantic search. Fully local, zero API keys required.

## Take

Its CLI can fail a commit or CI run with an exit code when architecture boundaries, complexity limits or co-change rules are broken, which jcodemunch's query-only tools don't do.

Codegraph builds a function-level dependency graph with tree-sitter, stores it in SQLite, and serves it through an MCP server and a CLI. Most of its MCP tools overlap jcodemunch and serena, so the MCP server isn't the reason to add it. What's new is the / gates and the git-diff impact analysis with co-change data, which could run as a script in pre-commit.sh or auto-maintain without changing the runtime.

Risk: It largely duplicates jcodemunch, so a trial run on one repo should confirm the gates and co-change signal add real value before it becomes another index to keep fresh.

Scores: tokens 3/5, accuracy 3/5, creativity 2/5, offline 5/5

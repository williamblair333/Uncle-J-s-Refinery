# Emmimal/memory-decay-engine

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/Emmimal/memory-decay-engine
- Stars: 12 (gh, 2026-11-15)
- Licence: MIT
- Last commit: 2026-07-25
- Source: discovered · Prompt and context compression (thin)

A pure-Python, zero-dependency memory decay engine for AI agent context — implements Ebbinghaus forgetting-curve retention with usage-based reinforcement, benchmarked against naive recency-window pruning.

## Take

memweave ranks hits by relevance only, and nothing in the stack decides which old memories to keep or let go based on how often they get recalled.

It's a small, pure-Python library with no dependencies. It scores memory items on a forgetting curve, so each recall makes an item last longer, and it ships with sanity checks and a benchmark against a plain recency window. It could sit as a script beside memweave, re-weighting or trimming what gets put into context. It passes the fit test, unlike the other four. context-chef is a TS SDK middleware, pi-dcp and dsh-argp are plugins for other agent runtimes, and or-cli depends on Microsoft's LLMLingua.

Risk: It's a research demo tested only on synthetic sessions, and its overlap with memweave's ranking may make the real gain small once it's wired in.

Scores: tokens 3/5, accuracy 2/5, creativity 3/5, offline 5/5

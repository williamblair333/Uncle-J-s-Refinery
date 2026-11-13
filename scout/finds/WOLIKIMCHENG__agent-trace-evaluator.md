# WOLIKIMCHENG/agent-trace-evaluator

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/WOLIKIMCHENG/agent-trace-evaluator
- Stars: 0 (gh, 2026-11-13)
- Licence: MIT
- Last commit: 2026-06-30
- Source: discovered · Evals and observability (thin)

Open-source evaluators for agent traces, tool calls, and LangGraph trajectories in Python and TypeScript.

## Take

Uncle J has no deterministic way to check that a session called the right tools, with the right arguments, in an acceptable order; outcomes and judge grade results with an LLM, not the path taken.

It's a small Python/TypeScript library of trajectory matchers (strict, superset or subset, with argument-matching modes), plus optional LLM-as-judge graders. Wrapped in a script, it could turn routing-policy rules like 'jcodemunch before Read' or 'memory_search first' into regression assertions over Claude Code transcripts or the bench harnesses. That checks accuracy without spending Claude tokens. The deterministic path runs fully offline; the judge path can stay unused or point at a local model.

Risk: It expects OpenAI/LangChain-style message and LangGraph shapes, so Claude Code transcripts need a converter, and a young project may not keep the API stable.

Scores: tokens 4/5, accuracy 4/5, creativity 2/5, offline 4/5

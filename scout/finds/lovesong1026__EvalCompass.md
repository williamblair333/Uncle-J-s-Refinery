# lovesong1026/EvalCompass

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/lovesong1026/EvalCompass
- Stars: 0 (gh, 2026-10-22)
- Licence: Apache-2.0
- Last commit: 2026-08-30
- Source: discovered · Evals and observability (thin)

Open-source AI evaluation framework with 80+ metrics, a unified 0–1 Score, and five dimensions  │ (correctness, groundedness, safety, trajectory, performance) for LLM agents, prompts & structured  │ outputs.

## Take

Uncle J has no deterministic, repeatable way to score agent runs or catch regressions; the outcomes and judge skills grade with an LLM, one run at a time, and the Langfuse traces behind dream and stats are only mined for playbooks and counts.

EvalCompass is a Python eval library with a CLI. Its core metrics are deterministic and need no API key, it keeps a JSON baseline to flag regressions, and it outputs JUnit results and exit codes for CI. Its Langfuse importer could turn the traces Uncle J already collects into scored eval cases, including MCP tool-call trajectories, so it adds a check without taking over the runtime. TokenSurf is a close runner-up, but it captures traces through a decorator in your own agent code, and Claude Code sessions don't run as Python functions you can wrap.

Risk: The README is mostly in Chinese and the project's maturity is unproven, so 80+ metrics may mean broad but shallow, and the Langfuse importer may not map Claude Code trace shapes cleanly without an adapter.

Scores: tokens 4/5, accuracy 4/5, creativity 2/5, offline 4/5

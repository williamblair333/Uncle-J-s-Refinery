# microsoft/LLMLingua

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/microsoft/LLMLingua
- Stars: 6770 (gh, 2026-10-24)
- Licence: MIT
- Last commit: 2026-09-10
- Source: discovered · Prompt and context compression (thin)

[EMNLP'23, ACL'24] To speed up LLMs' inference and enhance LLM's perceive of key information, compress the prompt and KV-Cache, which achieves up to 20x compression with minimal performance loss. 

## Take

Uncle J's retrieval tools cut how much gets fetched, but nothing shortens prose that is already retrieved (docs sections, web2md pages, memweave hits, logs) before it reaches the model.

LLMLingua is a Python library whose LLMLingua-2 model runs on the local machine and drops low-information tokens from text, so the compressed text is shorter but not reworded. It could sit behind a small compress tool in ask_local or a script that runs over web2md output, so the runtime stays Uncle J's. Like leanctx, it should only touch high-tolerance prose and never code, JSON or tool IDs; leanctx itself wraps SDK clients that Claude Code doesn't call directly.

Risk: Compression loses detail, so used on code, exact identifiers or evidence that tools cite, it would quietly drop facts and hurt accuracy, which is Bill's top goal; it needs strict allow-listing and a test on Uncle J's own data before use.

Scores: tokens 4/5, accuracy 2/5, creativity 2/5, offline 5/5

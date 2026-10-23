# Compressed `jcodemunch_guide` — measurement, benchmark and an upstream patch (2026-10-23)

ROADMAP item: "offline compress `_generate_claude_md_snippet()` output via cheap model;
benchmark 20 representative routing queries before/after; ~4,600–5,100 tokens/session
savings at full tier; upstream contribution to jcodemunch".

## What the guide is now (measured)

- Installed jcodemunch-mcp **1.108.391**. `jcodemunch-mcp claude-md --generate` (the same
  text `jcodemunch_guide` returns) is **2,804 characters**: a two-paragraph preamble, a
  4-step quick start, and an "All tools" catalogue naming 91 tools.
- **The ROADMAP's 4,600–5,100-token estimate is stale.** Upstream has since shrunk the
  snippet to a fraction of that. Also, nothing in this stack loads the guide per session:
  no CLAUDE.md, hook or script calls `jcodemunch_guide` (jcodemunch `search_text`, verdict
  `absent`). So the saving applies only to clients whose CLAUDE.md says "call
  jcodemunch_guide".
- The catalogue is **2,124 of the 2,804 chars (76%)**, and an MCP client already has all of
  it: every tool's name and description arrive with the server's tool list.

## Two ways to shrink it

| Variant | Chars | How | Risk |
|---|---|---|---|
| full | 2,804 | as shipped | — |
| compact | 680 | drop the "All tools" section, deterministically | names a client doesn't list would be lost; MCP clients list them all |
| llm | not measured | the local model rewrites the full text | can drop or alter tool names; needs re-running on every release; output isn't reproducible across models |

The deterministic cut needs no model, can't hallucinate, and stays correct as the tool list
changes, because it's generated from the same categories. That fits the improvement
program's "deterministic-first" principle better than LLM compression.

## Benchmark (built; the LLM half could not finish today)

`scripts/guide_bench/bench.py` with `scripts/guide_bench/queries.json` (20 routing requests,
each with its acceptable tools). The local model acts as router: it gets the tool-name
registry (as a real client has), one guide variant and one request, and must name one tool.
It scores full vs compact vs llm, counts tokens with the model's own tokenizer, and checks
that the llm variant kept every tool name.

```
just ask-local-up        # Heretic on :8090
.venv/bin/python scripts/guide_bench/bench.py --out state/guide-bench.json
```

**Result: not obtained.** On 2026-10-23 Heretic was generating at about 0.6 tokens/s (host
load average 17–22, Gitea Actions jobs running, 11.7 of 12.3 GB VRAM in use). The
compression call timed out twice (300 s, then 900 s; `state/ask_local.jsonl`). No accuracy
numbers are claimed here. Re-run the command above on an idle host. The run is cached
(`scripts/local_rail.py`), so a rerun only pays for calls that didn't finish.

## Upstream patch (ready, not filed)

`docs/proposals/2026-10-23-jcodemunch-guide-compact.patch` adds an optional
`compact: boolean` argument to `jcodemunch_guide`. When true, the catalogue is skipped and
the quick start plus routing guidance are kept. The default output is unchanged. It was made
against the installed 1.108.391 `server.py` and compiles. The upstream path is assumed to be
`src/jcodemunch_mcp/server.py`; rebase it before filing. It touches three places: the tool
schema, the handler, and `_generate_claude_md_snippet()`.

Before filing (Bill's call, like the other upstream filings): run the benchmark, so the
issue can say that compact routes as well as full on 20 queries; and check whether upstream
already has a tier or front-door mode that covers this (`_effective_surface() == "counter"`
returns a different snippet).

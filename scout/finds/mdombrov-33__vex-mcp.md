# mdombrov-33/vex-mcp

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/mdombrov-33/vex-mcp
- Stars: 2 (gh, 2026-11-02)
- Licence: MIT
- Last commit: 2026-06-20
- Source: eval

MCP proxy that blocks tool poisoning, rug pulls, and excessive agency in real time

## Evaluation

Verdict: **trial**

vex-mcp is a stdio proxy that sits in front of an MCP server's launch command. It checks tool catalogs for poisoning, hashes tool definitions to spot drift, and enforces allow and deny lists for each server. It also keeps a tamper-evident audit log. It fits as a wrapper without taking over the runtime: it is one config change per server, uses no model tokens, and its regex and Unicode checks should run fully offline once installed. Most of Uncle J's servers are first-party, so the main value is guarding the third-party servers started with / (context7, duckdb, serena) and limiting write-capable tools. The regex detectors can wrongly suppress a whole catalog, and the stack upgrades often, so a trial should come before adopting it.

### Trial sketch

Put a pinned, locally installed copy ( or , not ) in front of context7, duckdb and one jcodemunch instance, using a throwaway project  with the network off. Measure how many false flags or blocks the real tool catalogs trigger, how much drift noise comes after a jcodemunch or jdocmunch upgrade, the added round-trip time per tool call compared with the bench scripts, and whether a planted poisoned test server gets blocked. Token cost should stay at zero; check that blocked calls come back as short JSON-RPC errors and not long text.

### Risks

- Critical rules suppress the whole catalog, so one false positive on a first-party description (for example ask_local mentioning credential paths) could silently take a server's tools away
- Drift detection fires on every stack upgrade and will be noisy unless hashes are re-baselined in the upgrade or post-upgrade workflow
- The README's  usage breaks offline and pins nothing, so a security proxy could itself be swapped out from under you; install a pinned binary instead
- The checks are keyword and regex based, so a reworded injection gets past them; treat it as one layer of defence, not proof that a tool catalog is safe

# Trial hand-off: affaan-m/agentshield

Bill said yes twice: to the find and to the evaluation. Next step is a throwaway
spike **in a session with Bill**, in a separate working copy outside this repo,
measured against the current setup on tokens, accuracy and offline use.

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- Repo: https://github.com/affaan-m/agentshield
- Find page: scout/finds/affaan-m__agentshield.md

## Trial sketch

Build a pinned copy in a throwaway directory with network disabled. Run  with  against a copy of ~/.claude and the stack repo's mcp-clients config, never using --fix, --opus or --supply-chain-online. Hand-label each finding as true positive, false positive or noise, and record the runtime-confidence classification, wall-clock time and whether any network calls were attempted. Adopt only if real findings outnumber noise. If it's adopted, the JSON output would feed a refinery-doctor check at zero Claude tokens.

## Risks

- Likely false-positive flood on deliberate Uncle J patterns (2>/dev/null in hooks, uvx/npx launchers, many MCP servers), which would drag the score down without real risk
- Installing through npm/npx adds supply-chain exposure from Microsoft-owned npm infrastructure; the README's GitHub Action and GitHub App channels fail Bill's rule, so only a vendored local build is acceptable
- --fix rewrites config files and --opus sends config contents to a paid API, so both must stay off to keep it read-only and offline
- Single-author project tied to a wider plugin ecosystem with sponsor promotion, so rule quality and long-term upkeep are uncertain

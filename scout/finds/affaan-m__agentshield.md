# affaan-m/agentshield

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/affaan-m/agentshield
- Stars: 1402 (gh, 2026-11-14)
- Licence: MIT
- Last commit: 2026-10-18
- Source: eval

AI agent security scanner. Detect vulnerabilities in agent configurations, MCP servers, and tool permissions. Available as CLI, GitHub Action, ECC plugin, and GitHub App integration. 🛡️

## Evaluation

Verdict: **trial**

AgentShield is a Node CLI that statically scans a .claude/ directory and grades it on secrets, permissions, hooks, MCP servers and agent prompts. It can run as a script you call on demand without taking over the runtime, so it passes the fit test as long as it's run from a pinned local build, not through the GitHub Action or GitHub App channels. Uncle J has red-team and blue-team skills but no mechanical scanner for its own hooks and MCP registrations, so this fills a real gap on accuracy and offline use. The adoption-eval method assumes a backend is being replaced; nothing is replaced here, so read this as an additive-tool judgment. The rule count and the breach statistics in the README are the author's own claims and haven't been verified.

### Trial sketch

Build a pinned copy in a throwaway directory with network disabled. Run  with  against a copy of ~/.claude and the stack repo's mcp-clients config, never using --fix, --opus or --supply-chain-online. Hand-label each finding as true positive, false positive or noise, and record the runtime-confidence classification, wall-clock time and whether any network calls were attempted. Adopt only if real findings outnumber noise. If it's adopted, the JSON output would feed a refinery-doctor check at zero Claude tokens.

### Risks

- Likely false-positive flood on deliberate Uncle J patterns (2>/dev/null in hooks, uvx/npx launchers, many MCP servers), which would drag the score down without real risk
- Installing through npm/npx adds supply-chain exposure from Microsoft-owned npm infrastructure; the README's GitHub Action and GitHub App channels fail Bill's rule, so only a vendored local build is acceptable
- --fix rewrites config files and --opus sends config contents to a paid API, so both must stay off to keep it read-only and offline
- Single-author project tied to a wider plugin ecosystem with sponsor promotion, so rule quality and long-term upkeep are uncertain

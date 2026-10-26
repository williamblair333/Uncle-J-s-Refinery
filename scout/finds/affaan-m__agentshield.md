# affaan-m/agentshield

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/affaan-m/agentshield
- Stars: 1327 (gh, 2026-10-26)
- Licence: MIT
- Last commit: 2026-10-18
- Source: discovered · Secrets and supply-chain scanning (thin)

AI agent security scanner. Detect vulnerabilities in agent configurations, MCP servers, and tool permissions. Available as CLI, GitHub Action, ECC plugin, and GitHub App integration. 🛡️

## Take

Uncle J has no automated static audit of its own ~/.claude setup (settings permissions, hooks, MCP registrations, skills, CLAUDE.md) for hardcoded secrets, overly broad allow rules or hook-injection vectors.

AgentShield is a CLI that scans a Claude Code config directory for hardcoded secrets, broad permission rules, hook injection, MCP server risks and prompt-injection vectors. It can write a JSON report, so a script or justfile recipe could run it from refinery-doctor or the pre-commit or session-end checks without starting any servers, and only its findings would cost tokens. It is a better fit than snyk/agent-scan or cisco/mcp-scanner because it targets the Claude Code layout directly and needs no vendor API, but it overlaps with the cisco scanner's offline YARA mode, which is worth noting as an alternative for deeper MCP-server source scans.

Risk: It is a young npm package, so pulling it with npx is a supply-chain risk in itself and you should pin the version. Its heuristics may flag Uncle J's own deliberate hooks and permissions as false positives. Its --fix mode rewrites config files, including the deployed CLAUDE.md that install.sh overwrites, so run it report-only.

Scores: tokens 4/5, accuracy 3/5, creativity 2/5, offline 4/5

# alexgreensh/repo-forensics

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/alexgreensh/repo-forensics
- Stars: 205 (gh, 2026-11-06)
- Licence: NOASSERTION
- Last commit: 2026-11-05
- Source: discovered · Secrets and supply-chain scanning (thin)

Offline security scanner for AI-agent repos, skills, plugins, and MCP servers.

## Take

Uncle J has no dedicated scanner for checking third-party repos, skills, plugins and MCP servers for malicious content or supply-chain problems before they're installed.

It's a Python CLI that statically audits untrusted agent repos, and its README claims local operation, zero dependencies and no telemetry. It could run as a script behind the existing alternatives-scan download gate, inspecting a clone without executing its MCP servers, unlike snyk/agent-scan, which starts stdio servers to read their tool descriptions. It suits Bill's accuracy and offline goals, and a local scan spends no Claude tokens until findings are read.

Risk: Detection quality, false-positive rate and the offline claim are unverified README statements, and the self-updating rule feed and auto-scan integrations could add network use or hooks, so test it on known-good and known-bad repos and call it only as an explicit script.

Scores: tokens 4/5, accuracy 3/5, creativity 1/5, offline 5/5

# cisco-ai-defense/mcp-scanner

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/cisco-ai-defense/mcp-scanner
- Stars: 1119 (gh, 2026-11-17)
- Licence: Apache-2.0
- Last commit: 2026-11-16
- Source: discovered · Secrets and supply-chain scanning (thin)

Scan MCP servers for potential threats & security findings.

## Take

Uncle J runs eight-plus MCP servers and a growing skill library, but nothing checks their tool descriptions, prompts or server source for poisoning, hidden instructions or exfiltration before they're trusted.

It's a Python CLI, installed with uv, that scans MCP tools, prompts, resources and server source with YARA rules, and optionally with an LLM judge, a pip-audit dependency check and the Cisco AI Defense API. With the YARA rules and offline JSON-snapshot mode alone, it can run as a pre-registration or nightly script against the registered servers in mcp-clients/claude-code-mcp.json. The LLM judge could be pointed at the local model, which keeps it offline and cheap. Unlike snyk/agent-scan, its core detection doesn't rely on a vendor's analysis backend, so it beats the other candidates for this setup.

Risk: Its most visible engines are hosted: Cisco AI Defense, VirusTotal and pip-audit's advisory lookups. Run without them, the scan is only YARA plus whatever LLM it's given, which will miss subtle poisoning and may flag many harmless tools. Live scans also start the stdio servers they're scanning, so third-party configs need a sandbox.

Scores: tokens 3/5, accuracy 3/5, creativity 2/5, offline 3/5

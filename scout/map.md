---
reviewed: false
seeded: 2026-10-17T14:46:56Z
---
# Capability map

What the open-source landscape offers, laid over what Uncle J already covers.
Edit freely: change a status, rename a category, fix or add search queries
(separated by `; `). Set `reviewed: true` above to switch on nightly discovery.

| Category | Status | Why | Queries |
|---|---|---|---|
| Agent memory | covered | memweave already searches transcripts and the Obsidian vault across projects, and dream mines past traces into playbooks. | mcp server long-term memory agent local; knowledge graph memory mcp sqlite; episodic memory llm agent offline |
| Code intelligence | covered | jcodemunch handles symbol and structure retrieval, and serena adds real LSP for references and types. | mcp server code search tree-sitter; lsp mcp server multi-language; code graph mcp call hierarchy |
| Docs and library documentation retrieval | covered | jdocmunch covers Bill's own markdown, and context7 covers third-party libraries when Node is present. | offline library documentation mcp server; devdocs local mcp; markdown section retrieval mcp |
| Tabular data and SQL | covered | jdatamunch handles CSVs, and duckdb handles Parquet, joins and complex SQL. | mcp server sqlite postgres read-only; duckdb mcp server; spreadsheet xlsx mcp server |
| Local inference and model routing | thin | ask_local exposes one roughly 9B Ollama model for grunt work, with no task-based routing, fallback or local reranking. | llm router mcp local ollama; litellm proxy ollama routing |
| Evals and observability | thin | Langfuse traces, stats, judge and outcomes give per-session grading, but nothing runs repeatable regression evals on skills or routing. | agent trajectory evaluation open source |
| Sandboxed code execution | blank | No MCP or script runs untrusted or generated code in an isolated container or microVM. | mcp server sandbox code execution docker; firecracker sandbox llm code |
| Browser use and web automation | blank | Web access is limited to WebSearch and WebFetch, with no headless browser for interactive or JS-heavy pages. | playwright mcp server; browser automation mcp accessibility tree; headless browser agent local |
| Offline web search and research | thin | Web lookups depend on hosted WebSearch, which works against the offline goal, and there's no self-hosted metasearch or local crawl cache. | searxng mcp server; local web archive search mcp; deep research agent self-hosted ollama |
| Prompt and context compression | thin | The token economy rules, the MUNCH format and compress=True cut output, but nothing compresses long inputs or tool outputs in general. | prompt compression llmlingua; context pruning llm agent |
| Guardrails and prompt-injection defense | thin | The red-team, blue-team and telegram audit skills plus jscrub are manual or narrow, with no runtime filter on untrusted tool or web content. | prompt injection detection local model; mcp security proxy tool poisoning; llm guardrails offline classifier |
| Secrets and supply-chain scanning | thin | jscrub, pin-canary and the push guards cover some ground, but no MCP or skill audits dependencies, licences or MCP server manifests. | secret scanning pre-commit gitleaks; mcp server security scanner; sbom vulnerability scan cli offline |
| Multi-agent orchestration | thin | The orchestrator manifests, ralph loops, referee and per-task-review-cycle exist, but there's no lightweight task queue or shared blackboard as an MCP. | mcp task queue agents; multi-agent blackboard mcp; agent task manifest runner cli |
| Code review and verification | covered | judge, smart-review, adversarial-review, referee and first-run-gate already run layered pre-merge checks. | ai code review cli local llm; static analysis mcp semgrep; mutation testing llm assisted |
| Scheduling and maintenance automation | covered | Cron jobs, auto-maintain, healthcheck notifications, refinery-doctor and the stack-alerts scripts keep the stack running on their own. | cron mcp server schedule; systemd timer llm agent |
| Messaging gateways and notifications | covered | The Telegram gateway, session notifications and inline buttons already give a hardened remote channel. | ntfy mcp server notifications; signal cli llm bridge |
| Document ingestion and OCR | thin | Only the reading-screenshot-documents skill handles PDFs, office files and images, and there's no local OCR or layout-parsing MCP. | pdf to markdown local ocr mcp; docling mcp server |
| Voice and wake word | blank | No speech-to-text, text-to-speech or wake-word path exists for hands-free or offline voice interaction. | whisper.cpp mcp server; openwakeword local assistant; piper tts mcp |

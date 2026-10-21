# firecrawl/firecrawl

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/firecrawl/firecrawl
- Stars: 192987 (gh, 2026-10-19)
- Licence: AGPL-3.0
- Last commit: 2026-10-19
- Source: top100 · GitHub top 100 (first sweep)

Supercharge your AI agents with data from the web and beyond. Building the library for superintelligence. 🔥

## Take

Uncle J has no structured web-ingestion tool: WebFetch returns one page at a time with no crawling, no clean markdown and no batch extraction, so web research costs a lot of tokens.

Firecrawl crawls and scrapes sites into clean markdown or structured JSON, and it ships an MCP server, so it can plug in next to jdocmunch and markitdown without taking over the runtime. Crawled docs could be saved to disk and indexed by jdocmunch, which would turn repeated web lookups into cheap local retrieval. The other candidates are reading lists, full runtimes that would replace Uncle J (openclaw, hermes-agent, opencode, n8n), or tools Uncle J already has (superpowers, markitdown, the REA-based clean-room skill, grill-me-style skills).

Risk: The self-hosted version needs Docker, Redis and a headless browser and has fewer features than the hosted API, so it's tempting to fall back on the cloud service, which sends queries off the machine and depends on the network.

Scores: tokens 4/5, accuracy 3/5, creativity 3/5, offline 2/5

# feder-cr/invisible_playwright_mcp

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/feder-cr/invisible_playwright_mcp
- Stars: 878 (gh, 2026-11-10)
- Licence: MIT
- Last commit: 2026-10-21
- Source: discovered · Browser use and web automation (blank)

Playwright MCP server undetected by anti-bots and captchas: AI agent browses the web on anti-detect stealth Firefox, Python, undetected browser automation, scraping, computer use.

## Take

Uncle J can already drive a browser through firefox-mcp.sh and turn pages into markdown with web2md.py, but it has nothing for sites whose anti-bot checks or captchas block normal automation.

It's a Python MCP server, launched with uvx, that drives a patched stealth Firefox. You can pin its browser identity with a seed and route it through a proxy. In MCP mode Claude does the reasoning, so it plugs in like the other servers. The OpenRouter key is only needed for its optional standalone web UI. It's the only candidate here that adds a new capability. Plain mcp-playwright mostly repeats the existing Firefox route, browser-use needs an OpenAI key, DevDocs is unmaintained and overlaps context7/web2md, and design-extract is a narrow design-token tool.

Risk: Getting around anti-bot protection can break site terms of service, and it downloads a pinned engine binary from a stranger, so the binary should be checked and the server sandboxed before it touches real accounts or profiles.

Scores: tokens 2/5, accuracy 3/5, creativity 3/5, offline 3/5

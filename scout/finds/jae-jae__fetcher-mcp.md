# jae-jae/fetcher-mcp

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/jae-jae/fetcher-mcp
- Stars: 1088 (gh, 2026-10-30)
- Licence: MIT
- Last commit: 2026-01-14
- Source: discovered · Browser use and web automation (blank)

MCP server for fetch web page content using Playwright headless browser.

## Take

It lets Uncle J fetch pages that need JavaScript to render and get back clean Markdown, a job web2md.py likely can't do on JS-heavy pages and firefox-mcp.sh only does through full interactive driving.

It's a small MCP server that drives headless Chromium through Playwright, strips each page down to its main content with Readability, and returns Markdown or HTML. It skips images, stylesheets and fonts when loading, and it can fetch several URLs in parallel. That means fewer tokens per page than a full browser-automation server, and it plugs in as one npx MCP entry without taking over the runtime.

Risk: It may overlap with the existing firefox-mcp.sh and web2md.py, and Readability can silently drop content on pages that aren't articles, such as docs tables or app UIs.

Scores: tokens 4/5, accuracy 3/5, creativity 2/5, offline 3/5

# DasDigitaleMomentum/searxNcrawl

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/DasDigitaleMomentum/searxNcrawl
- Stars: 180 (gh, 2026-10-23)
- Licence: MIT
- Last commit: 2026-10-21
- Source: discovered · Offline web search and research (thin)

Open-source MCP server that gives AI agents web search (SearXNG) and clean Markdown crawling of pages, whole sites and logged-in areas. Self-hosted, no API key. Firecrawl-compatible API planned.

## Take

Uncle J has no self-hosted search backend: web lookups go through hosted WebSearch/WebFetch, and web2md.py only converts single pages.

It's a Python MCP server, launched with uvx, that pairs a local SearXNG instance with Crawl4AI. It returns clean Markdown for single pages, whole documentation sites and logged-in areas, with repeated blocks stripped, which keeps token cost down. It plugs in alongside the other uvx-launched servers without taking over the runtime, and with SearXNG it needs no API key.

Risk: It needs a SearXNG container running plus Playwright and Crawl4AI, which is a heavy dependency stack. The crawled pages are untrusted content entering the context, so they can carry prompt injection.

Scores: tokens 4/5, accuracy 4/5, creativity 3/5, offline 3/5

## Verdict (reviewed 2026-10-23): no, already have it

Read-only check (gh api: repo, `pyproject.toml`, README; nothing cloned or run).

- **Microsoft:** `playwright>=1.40.0` is a direct dependency, and Crawl4AI renders every page
  in Playwright's Chromium (about 550 MB, downloaded on the first crawl). Bill avoids both.
- **Already covered:** SearXNG runs here (`/opt/docker/searnx`, `127.0.0.1:8086`, used by the
  chat page's web search), and `just web2md` (trafilatura, no browser) turns pages and sitemaps
  into markdown for jdocmunch.
- **Still missing:** SearXNG as a tool Claude Code can call. A small stdlib wrapper around the
  local instance's JSON API would do that without Playwright, if it's wanted.
- Facts: MIT, 181 stars, last push 2026-10-21, v0.32.0. Deps: crawl4ai, playwright, fastmcp,
  httpx, tldextract, python-dotenv. The README mentions no telemetry.

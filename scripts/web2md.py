# /// script
# requires-python = ">=3.10"
# dependencies = ["trafilatura==2.0.0"]
# ///
"""web2md — fetch web pages as markdown files, so repeat lookups become local retrieval.

Replaces the firecrawl idea (review/2026-10-19-firecrawl.md: 7 services, a Playwright
browser). trafilatura is one process, Apache-2.0, no browser; it returned about half of
firecrawl's markdown on the same pages in 1-2 s.

    uv run --script scripts/web2md.py URL [URL ...] --out DIR           # those pages
    uv run --script scripts/web2md.py URL --sitemap --out DIR [--max N] # the site's sitemap
    uv run --script scripts/web2md.py URL --crawl --out DIR [--max N]   # same-host links
    just web2md …                                                       # the same

Each page becomes DIR/<host>/<path-slug>.md with a small front matter block (source URL,
fetch date, title). Then index the folder: jdocmunch `index_local(paths=[DIR])`.
JavaScript-rendered pages come back empty: this fetches HTML, it doesn't run a browser.
Prints a JSON summary; exits 1 when nothing was written.

Measured 2026-10-22: good for prose pages; weak for code-heavy docs. On
docs.astral.sh/uv/guides/scripts/ it kept 6 of 8 shell commands (tabbed code blocks are lost),
code blocks come out unfenced (so a `# comment` line reads as a heading), and relative links
can resolve against the wrong base. For a named library's API docs, context7 is better.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

_SAFE = re.compile(r"[^a-z0-9._-]+")


def slug(text: str, limit: int = 120) -> str:
    """Lowercase, [a-z0-9._-] only, no leading dots; never empty."""
    s = _SAFE.sub("-", text.lower()).strip("-.")
    return s[:limit].strip("-.") or "index"


def out_path(out_dir: Path, url: str) -> Path:
    """DIR/<host>/<path-slug>.md, refusing anything that would land outside DIR."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"not an http(s) URL: {url!r}")
    path = parts.path.strip("/")
    if parts.query:
        path += "-" + parts.query
    target = (out_dir / slug(parts.hostname) / f"{slug(path)}.md").resolve()
    if not target.is_relative_to(out_dir.resolve()):
        raise ValueError(f"refusing to write outside {out_dir}: {url!r}")
    return target


def render(url: str, markdown: str, title: str | None, fetched: str) -> str:
    head = ["---", f"source: {url}", f"fetched: {fetched}"]
    if title:
        head.append("title: " + json.dumps(title, ensure_ascii=False))
    return "\n".join(head + ["---", "", markdown.strip(), ""])


def page_urls(start: str, mode: str, limit: int) -> list[str]:
    if mode == "sitemap":
        from trafilatura import sitemaps
        found = sitemaps.sitemap_search(start)
    elif mode == "crawl":
        from trafilatura.spider import focused_crawler
        _, known = focused_crawler(start, max_seen_urls=limit, max_known_urls=limit * 10)
        host = urlsplit(start).hostname
        found = [u for u in known if urlsplit(u).hostname == host]
    else:
        found = [start]
    seen, out = set(), []
    for u in found:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:limit]


# A line that is only `[Title](…#anchor)` is a heading trafilatura turned into a link
# (docs sites put a permalink anchor on every heading).
_HEADING_LINK = re.compile(r"^\[([^\]\n]+)\]\([^)\s]*#[^)\s]*\)\s*$", re.M)


def fix_headings(md: str, title: str | None) -> str:
    """Turn heading-links back into headings: `# ` for the page title, `## ` for the rest.

    Without this jdocmunch sees one section per page. The original levels aren't recoverable
    from trafilatura's markdown (its XML keeps them but drops code blocks, measured on
    docs.astral.sh), so every non-title heading is level 2.
    """
    def repl(m):
        text = m.group(1).strip()
        return ("# " if title and text == title.strip() else "## ") + text
    md = _HEADING_LINK.sub(repl, md)
    return _PILCROW.sub("", md)   # Sphinx's `## Title[¶](…#title)` permalink


_PILCROW = re.compile(r"\[¶\]\([^)\s]*\)")


def fetch_markdown(url: str) -> tuple[str | None, str | None]:
    import trafilatura
    html = trafilatura.fetch_url(url)
    if not html:
        raise RuntimeError("fetch failed (unreachable, blocked, or not HTTP 200)")
    md = trafilatura.extract(html, url=url, output_format="markdown", include_links=True,
                             include_tables=True, include_comments=False)
    meta = trafilatura.extract_metadata(html)
    title = meta.title if meta else None
    return (fix_headings(md, title) if md else None), title


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--out", required=True, type=Path)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--sitemap", action="store_true", help="pages from the site's sitemap")
    mode.add_argument("--crawl", action="store_true", help="follow same-host links")
    ap.add_argument("--max", type=int, default=50, help="page cap per start URL (default 50)")
    args = ap.parse_args(argv)
    how = "sitemap" if args.sitemap else "crawl" if args.crawl else "page"
    fetched = dt.date.today().isoformat()
    written, failed, total = [], [], 0
    for start in args.urls:
        for url in page_urls(start, how, args.max):
            try:
                target = out_path(args.out, url)
                md, title = fetch_markdown(url)
            except Exception as e:  # one bad page must not stop the run
                failed.append({"url": url, "error": f"{type(e).__name__}: {e}"[:200]})
                continue
            if not md:
                failed.append({"url": url, "error": "no main text (JS-rendered or not HTML?)"})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            text = render(url, md, title, fetched)
            target.write_text(text, encoding="utf-8")
            total += len(text.encode())
            written.append(str(target))
            print(f"ok   {url} -> {target}", file=sys.stderr)
    for f in failed:
        print(f"fail {f['url']}: {f['error']}", file=sys.stderr)
    print(json.dumps({"written": len(written), "failed": len(failed), "bytes": total,
                      "out": str(args.out), "failures": failed[:20]}))
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())

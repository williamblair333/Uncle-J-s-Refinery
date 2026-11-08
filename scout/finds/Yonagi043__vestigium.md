# Yonagi043/vestigium

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/Yonagi043/vestigium
- Stars: 12 (gh, 2026-11-08)
- Licence: MIT
- Last commit: 2026-10-28
- Source: discovered · Document ingestion and OCR (thin)

Every answer leaves a trace back to its page. An MCP server that lets AI agents read long PDFs by address and cite the pages.

## Take

Uncle J can convert documents to Markdown with markitdown and index its own markdown with jdocmunch, but it has no structured, address-based way to read long or scanned PDFs with page-level citations.

Vestigium is an MCP server that uses Docling, with OCR for scans, to turn a PDF into addressable sections, pages, tables and footnotes, so the agent reads original text by address and cites the page. It's effectively the munch pattern for PDFs: no embeddings, vector store or model calls to build the index, and retrieval stays outline-first. Its own tests claim Haiku matched whole-text accuracy at about half the cost, which would suit Bill's accuracy and token goals and his delegate-to-cheaper-models habit.

Risk: The benchmarks are self-reported and AI-graded with no human spot check, and the project looks early, so accuracy and Docling parse quality need testing on Bill's own messy PDFs before it earns a routing-table slot.

Scores: tokens 5/5, accuracy 4/5, creativity 3/5, offline 4/5

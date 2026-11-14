# Yonagi043/vestigium

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/Yonagi043/vestigium
- Stars: 13 (gh, 2026-11-14)
- Licence: MIT
- Last commit: 2026-10-28
- Source: eval

Every answer leaves a trace back to its page. An MCP server that lets AI agents read long PDFs by address and cite the pages.

## Evaluation

Verdict: **trial**

Vestigium is a local stdio MCP server. It parses a PDF once with Docling, with OCR for scans, builds a BM25 index with no embeddings and no model calls, and lets the agent read by address (sections, pages, tables, notes) with a PDF page attached to every passage. That fills a real gap: Uncle J has no PDF route that passes the fit test, since markitdown is Microsoft and ruled out. It also matches Bill's goals in order: page-cited answers for accuracy, reading by address for token efficiency, and offline indexing. But the project is at 0.1.x, and every benchmark was run by the author, graded by an AI judge with no human check, and tested only in Claude Code. A throwaway trial should come before any routing change.

### Trial sketch

Install it into a separate venv with VESTIGIUM_HOME pointing at a temp dir, and ingest 3–5 long PDFs Bill actually uses, including one scanned PDF. Network must be off during ingest and querying. Ask about 20 questions whose answers you've already checked by hand. Compare Vestigium with the whole text read through jdocmunch/Read: score accuracy and citation correctness yourself, not with an AI judge, and log tokens and time per answer from the session. Also check Docling's dependency tree (OCR backend, any onnxruntime pull) against the Microsoft rule before keeping it.

### Risks

- Docling's dependency tree, OCR backend and model downloads could pull in Microsoft code (e.g. onnxruntime) or need network on first ingest; check before relying on offline use
- Very young 0.1.x project; the benchmarks are the author's own and AI-graded with no human check, so the cost and accuracy numbers aren't independently verified
- The optional 'rules' tool lets the agent change how documents are read, so text inside an untrusted PDF could try to steer it; keep it off
- Parse quality varies from PDF to PDF, and the author's figure-question score was low (33% with Haiku), so check the quality report each ingest writes

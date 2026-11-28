# NameetP/pdfmux

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/NameetP/pdfmux
- Stars: 88 (gh, 2026-11-26)
- Licence: MIT
- Last commit: 2026-11-24
- Source: discovered · Document ingestion and OCR (thin)

PDF extraction that audits its own output — and certifies any other extractor's, catching pages they silently dropped. Verify signed manifests offline: free, MIT, no account. 0.903 on opendataloader-bench, #2 of 8 engines. 7-tool MCP server.

## Take

Uncle J has no PDF or OCR ingestion that passes the fit test, because the existing markitdown skill is Microsoft code and is ruled out.

pdfmux is a Python CLI and MCP server. It sends each PDF page to a local extractor (PyMuPDF, RapidOCR, Docling and others), checks what came back, re-extracts pages that failed and flags pages it still can't read instead of dropping them silently. That check on its own output serves accuracy, William's first goal, and its  mode can also check any other extractor's output. It installs as a script or an MCP server, so Uncle J stays the runtime, and markdown chunks with token caps feed straight into jdocmunch.

Risk: The heavier backends (Docling, Surya, Marker) download model weights on first use, and the LLM fallback can point at hosted APIs (Gemini, Mistral OCR), so offline use depends on caching models ahead of time and turning off the hosted fallbacks in config.

Scores: tokens 4/5, accuracy 4/5, creativity 3/5, offline 4/5

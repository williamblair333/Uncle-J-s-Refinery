# haris-musa/excel-mcp-server

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/haris-musa/excel-mcp-server
- Stars: 4322 (gh, 2026-11-22)
- Licence: MIT
- Last commit: 2026-11-20
- Source: discovered · Tabular data and SQL (covered)

Excel MCP server: let AI (Claude, Cursor, Codex) create and edit Excel files with charts, PivotTables, slicers and formulas. No Excel required.

## Take

Uncle J can read CSV through jdatamunch and run SQL through duckdb, but nothing in the stack can create or edit .xlsx workbooks with formulas, charts or PivotTables.

It's a Python MCP server built on openpyxl. It reads, writes and calculates Excel workbooks locally, with no Excel install, and runs over stdio, so Uncle J stays the runtime. Reads come back in pages within set size limits, which keeps token cost down on big sheets. Its formula tracing and step-by-step evaluation help answer why a spreadsheet number is wrong.

Risk: Its own formula engine can still return values that differ from real Excel on edge cases, and those values could be acted on as if true. Check its project install route works offline and doesn't depend on its website.

Scores: tokens 4/5, accuracy 3/5, creativity 3/5, offline 5/5

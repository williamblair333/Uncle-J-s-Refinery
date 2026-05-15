---
repo: MemPalace/mempalace
title: "repair --yes leaves orphaned collections on repeat runs"
type: bug
status: pending
issue_url: ""
---

**What happened?**
Running `repair --yes` twice in the same session created two full collections in SQLite. The orphaned collection retained all 10,000+ embeddings with no CLI way to remove it, adding ~100 MB of unrecoverable bloat.

**What did you expect?**
`repair` should replace the existing collection, not add alongside it. Database size after repair should match a fresh mine.

**How to reproduce:**
1. Run `mempalace repair --yes`
2. Run `mempalace repair --yes` again
3. Check: `SELECT COUNT(*) FROM collections` — returns 2+
4. Check file size — grows ~100 MB per extra run

**Environment:**
- OS: Linux (Debian/Ubuntu, Liquorix kernel 6.x)
- Python version: 3.11
- MemPal version: 3.3.5

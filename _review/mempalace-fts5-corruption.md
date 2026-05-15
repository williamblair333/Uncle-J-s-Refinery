---
repo: MemPalace/mempalace
title: "FTS5 index corrupts after multiple repair --yes runs"
type: bug
status: pending
issue_url: ""
---

**What happened?**
After running `repair --yes` twice, `PRAGMA quick_check` on `chroma.sqlite3` returned `malformed inverted index for FTS5 table main.embedding_fulltext_search`. Subsequent `mine` runs and MCP searches failed silently. Manual fix required:

```sql
INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('rebuild');
```

**What did you expect?**
`repair` should leave the database fully consistent. FTS5 should be valid after any number of repair runs.

**How to reproduce:**
1. Run `mempalace repair --yes`
2. Run `mempalace repair --yes` again
3. Open `chroma.sqlite3` and run `PRAGMA quick_check`
4. Observe: `malformed inverted index for FTS5 table main.embedding_fulltext_search`

**Environment:**
- OS: Linux (Debian/Ubuntu, Liquorix kernel 6.x)
- Python version: 3.11
- MemPal version: 3.3.5

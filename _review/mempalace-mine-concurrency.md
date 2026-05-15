---
repo: MemPalace/mempalace
title: "mine has no concurrency guard — concurrent invocations exhaust RAM"
type: bug
status: pending
issue_url: ""
---

**What happened?**
Two `mine` invocations fired simultaneously (SessionStart + Stop hook overlapping). Each spawned an independent Python process loading the full HNSW into RAM. On a 14 GB machine with a 10,000-drawer palace this consumed ~1.6 GB per extra process, exhausted swap, triggered OOM kills, and left the HNSW partially written.

**What did you expect?**
A second `mine` invocation while one is already running should detect the conflict, skip gracefully, and exit 0 so calling hooks don't fail.

**How to reproduce:**
1. Configure two hooks that both call `mempalace mine` (e.g. SessionStart + Stop)
2. End a session — both hooks fire within seconds of each other
3. Watch `htop` — multiple Python processes each loading the full HNSW

**Environment:**
- OS: Linux (Debian/Ubuntu, Liquorix kernel 6.x)
- Python version: 3.11
- MemPal version: 3.3.5

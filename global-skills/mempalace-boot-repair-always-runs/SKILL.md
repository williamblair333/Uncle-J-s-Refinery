---
name: mempalace-boot-repair-always-runs
description: Use when HNSW shows 0 elements at session start after a system reboot, a long-running repair process is already active, and the palace appeared healthy before shutdown. Distinct from link_lists.bin corruption — SQLite is intact, repair will succeed, but will repeat on every future reboot.
---

## When to use

- HEALTHCHECK reports `mempalace-hnsw-drift` or HNSW = 0
- A `mempalace-repair-now.sh` process is already running (check `ps aux | grep repair`)
- The system rebooted recently (`uptime` or `who -b` confirms it)
- SQLite drawer count is large and intact (not a wipe — the data is fine)
- The pattern repeats: HNSW is rebuilt, works fine, but is 0 again after the next reboot

Do NOT use `mempalace-hnsw-corruption-fix` for this pattern — that skill targets `link_lists.bin` bloat from the Rust binding bug. This pattern is a scheduling problem, not corruption.

## Diagnosis

### Step 1 — Confirm repair is already running

```bash
ps aux | grep mempalace-repair | grep -v grep
# PID, elapsed time, RSS, CPU
```

If it shows >1 GB RSS and elapsed >5 min after reboot, it started from `@reboot`.

### Step 2 — Check the repair log

```bash
tail -50 /opt/proj/Uncle-J-s-Refinery/state/mempalace-repair.log
```

Look for timestamp near last boot. If it matches, `@reboot` triggered it.

### Step 3 — Confirm the cron entry

```bash
crontab -l | grep -E "@reboot|mempalace-repair"
```

The smoking-gun entry:
```
@reboot sleep 120 && flock -n /tmp/mempalace-repair.lock bash mempalace-repair-now.sh >> ...
```

This runs **unconditionally on every boot** — even when HNSW was healthy at shutdown.

### Step 4 — Estimate time remaining

~89 min for 235 K rows, scales linearly. Check current count:

```bash
sqlite3 ~/.mempalace/palace/chroma.sqlite3 \
  "SELECT count(*) FROM embeddings;" 2>/dev/null
```

Watch repair finish:
```bash
watch -n5 'ps -p <PID> -o pid,etime,rss,pcpu --no-headers 2>/dev/null || \
  (echo "DONE"; ls -lh ~/.mempalace/palace/*/link_lists.bin)'
```

## Fix — make boot repair conditional

### 1. Create `scripts/mempalace-boot-repair-if-needed.sh`

```bash
#!/usr/bin/env bash
# Only run repair if HNSW is actually missing or severely drifted.
SQLITE_COUNT=$(sqlite3 ~/.mempalace/palace/chroma.sqlite3 \
  "SELECT count(*) FROM embeddings;" 2>/dev/null || echo 0)
LINK_LISTS=$(find ~/.mempalace/palace -name "link_lists.bin" -size +1c 2>/dev/null | wc -l)

if [[ "$LINK_LISTS" -gt 0 && "$SQLITE_COUNT" -gt 0 ]]; then
  echo "$(date): HNSW appears healthy ($LINK_LISTS segments, $SQLITE_COUNT rows) — skipping boot repair"
  exit 0
fi

echo "$(date): HNSW missing or empty — running repair (SQLite rows: $SQLITE_COUNT)"
exec bash /opt/proj/Uncle-J-s-Refinery/scripts/mempalace-repair-now.sh
```

### 2. Swap the crontab entry

```bash
crontab -e
```

Replace:
```
@reboot sleep 120 && flock -n /tmp/mempalace-repair.lock bash mempalace-repair-now.sh >> ...
```

With:
```
@reboot sleep 120 && flock -n /tmp/mempalace-repair.lock bash /opt/proj/Uncle-J-s-Refinery/scripts/mempalace-boot-repair-if-needed.sh >> /opt/proj/Uncle-J-s-Refinery/state/mempalace-repair.log 2>&1
```

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Running a second repair on top of the running one | Wait for in-flight repair to finish — it will succeed |
| Treating HNSW=0 as corruption | Check `ps aux` and repair log first — it may just be a rebuild in progress |
| Checking `link_lists.bin` for size immediately | File is 0 bytes while rebuild is writing; it grows at the end |
| Killing the in-flight repair | Let it finish; killing mid-run leaves HNSW at 0 with no archive |

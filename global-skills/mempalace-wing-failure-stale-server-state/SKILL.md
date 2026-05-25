
---
name: mempalace-wing-failure-stale-server-state
description: Diagnose MemPalace wing-level HNSW failures caused by stale in-memory state in a running MCP server — distinct from disk corruption. Use when wing searches fail but global search works, and reconnect doesn't fix it.
---

# MemPalace Wing Failure — Stale MCP Server HNSW State

## When to use

- Wing-scoped searches fail with HNSW errors but `mempalace_search` (global) works fine
- `mempalace_reconnect` does not fix the wing errors
- The palace was recently rebuilt or repaired before the errors appeared
- No abnormal `link_lists.bin` file sizes (that's [[mempalace-hnsw-corruption-fix]], not this)

## Failure signature

wing: uncle_j_s_refinery → HNSW error
wing: sessions            → HNSW error
global search             → OK
wing: conversations       → OK

The running MCP server's in-process C++ hnswlib object is stale — it was
loaded before the palace rebuild and survived `reconnect` because reconnect
only resets the Python-level cache, not the native heap object.

## Diagnostic steps

**Step 1 — Map which wings fail**

Run a search scoped to each major wing. Note: if global works and ≥1 wing
fails, the issue is almost certainly server-side state, not disk corruption.

**Step 2 — Attempt reconnect**

mempalace_reconnect()

Re-test the failing wings. If still failing → proceed.

**Step 3 — Confirm disk is healthy via direct ChromaDB call**

Run a direct Python test outside the MCP server process:

python3 - <<'EOF'
import chromadb
client = chromadb.PersistentClient(path=os.path.expanduser("~/.mempalace/palace"))
col = client.get_collection("mempalace_drawers")
results = col.query(query_texts=["test"], n_results=3, where={"wing": "uncle_j_s_refinery"})
print(len(results["ids"][0]), "results")
EOF

If direct call succeeds → disk is healthy, issue is the running server.

**Step 4 — Confirm via fresh subprocess**

python3 - <<'EOF'
# Same query through a fresh server instantiation
EOF

If fresh subprocess works → the in-memory HNSW in the running MCP server
process is stale.

## Fix

Restart the MCP server so it loads a fresh in-memory HNSW from disk.

In Claude Code: the MCP server typically auto-restarts when Claude Code
restarts. Exit and reopen Claude Code, then re-test the failing wings.

If the server runs as a daemon:

pkill -f "mempalace"
# Claude Code will auto-restart it on next tool call

## Post-fix verification

mempalace_search(query="test", wing="uncle_j_s_refinery", limit=1)
mempalace_search(query="test", wing="sessions", limit=1)

Both should return results without HNSW errors.

## Distinction from disk corruption

| Symptom | Stale server state (this skill) | Disk corruption ([[mempalace-hnsw-corruption-fix]]) |
|---|---|---|
| Direct ChromaDB calls | ✅ Work | ❌ Fail |
| Fresh subprocess | ✅ Works | ❌ Fails |
| `link_lists.bin` size | Normal | Hundreds of GB |
| Fix | Restart server | Rebuild HNSW index |

## Common trigger

This failure mode typically appears immediately after `mempalace repair`
or a palace rebuild — the server process loaded the old HNSW before the
rebuild completed and its in-memory state was not refreshed.

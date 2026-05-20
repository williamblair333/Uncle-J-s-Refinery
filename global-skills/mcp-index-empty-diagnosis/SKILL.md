---
name: mcp-index-empty-diagnosis
description: Diagnose and fix an MCP retrieval tool (jdocmunch, jcodemunch, jdatamunch) that is registered and running but silently returns empty results due to an unpopulated index. Also wires in preventive measures so the gap can't recur silently.
---

## When to use

A search/retrieval MCP tool (`doc_list_repos`, `search_sections`, `list_repos`, `list_datasets`) returns `[]` or empty results despite the tool being registered and healthy. No error is raised — it just returns nothing.

## Root cause pattern

The index directory was created (by install or upgrade) but the index command was never run. The tool is alive; it just has nothing to serve.

## Diagnosis steps

1. **Check the index directory** — look for the tool's state directory:
   - jdocmunch: `~/.doc-index/`
   - jcodemunch: `~/.code-index/` (or configured path)
   - jdatamunch: `~/.data-index/`

2. **If empty** (directory exists but no files/subdirs), the index was never populated.

3. **Run the index command** (one-time fix):
# jdocmunch
/opt/proj/Uncle-J-s-Refinery/.venv/bin/jdocmunch-mcp index-local /opt/proj/Uncle-J-s-Refinery

# jcodemunch
/opt/proj/Uncle-J-s-Refinery/.venv/bin/jcodemunch-mcp index-repo /opt/proj/Uncle-J-s-Refinery

# jdatamunch
/opt/proj/Uncle-J-s-Refinery/.venv/bin/jdatamunch-mcp index-local /opt/proj/Uncle-J-s-Refinery

4. **Verify** — call the list/verify tool to confirm the index now has content:
/opt/proj/Uncle-J-s-Refinery/.venv/bin/jdocmunch-mcp verify-index

## Wire in preventive measures (do all three)

### A. `install.sh` — index on every install/re-install
Add a step after the tool install step:
# Step 4d: populate jdocmunch index
jdocmunch-mcp index-local "$STACK_ROOT" >> .install-jdm-index.log 2>&1

### B. `post-merge-hook.sh` — re-index when source files change
After a `git pull`, detect relevant file changes and re-index silently:
CHANGED=$(git diff-tree --no-commit-id -r --name-only HEAD)
if echo "$CHANGED" | grep -qE '\.(md|rst|txt)$'; then
  jdocmunch-mcp index-local "$STACK_ROOT" >> state/post-merge.log 2>&1
fi

### C. `healthcheck.sh` — fail fast if index is empty
Add a check that fails with a clear fix hint:
# check 9h: jdocmunch index populated
if [ -z "$(ls -A ~/.doc-index/ 2>/dev/null)" ]; then
  echo "FAIL check 9h: ~/.doc-index/ is empty — run: jdocmunch-mcp index-local $STACK_ROOT"
  FAIL=1
else
  echo "OK   check 9h: jdocmunch index populated"
fi

## Key principle

Indexing tools create their state directories on install but do **not** self-populate. Any tool that depends on an index must either populate it at install time or have a healthcheck that catches the gap before a user session runs silently against an empty corpus.

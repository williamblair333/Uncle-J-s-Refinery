---
name: post-upgrade-mcp-integration
description: After any MCP stack upgrade, systematically discover new tools and integrate them into CLAUDE.md routing rules without being asked
type: process
---

## When to use

After any upgrade to jcodemunch, jdatamunch, jdocmunch, mempalace, serena, or any other MCP server. Trigger immediately on detecting a version bump — don't wait for a user request.

## Steps

### 1. Check for prior work
mempalace_search("upgrade integration <tool-name>")
Skip steps already done in a prior session.

### 2. Enumerate current tools
ToolSearch("select:<mcp-namespace>__*", max_results=100)
Run once per upgraded server. Capture the full tool list.

### 3. Diff against CLAUDE.md
Read the routing table in both `/home/bill/.claude/CLAUDE.md` and the project's `CLAUDE.md`. Identify:
- Tools in the MCP namespace that aren't mentioned
- Tools mentioned that no longer exist (dropped or renamed)

### 4. Categorize new tools
Group by function (retrieval, navigation, quality, bridging, schema, index management). Use the existing sub-category structure as a template — don't invent new categories unless there's no fit.

### 5. Update both CLAUDE.md files
Add new tools under their category with a one-line description of when to prefer them over adjacent tools. Remove or update stale entries. Keep the routing table scannable — no walls of prose.

### 6. Clean up redundant memories
If a MemPalace memory covers behavior now captured in a skill or CLAUDE.md rule, remove the memory. Memory is for facts that aren't derivable from config; routing rules belong in CLAUDE.md.

### 7. Snapshot
mempalace_diary_write("Integrated <tool> vX.Y — added N tools across K categories")

### 8. Clear post-upgrade flag
```bash
rm -f /opt/proj/Uncle-J-s-Refinery/state/post-upgrade-needed
```
This flag is written by the async upgrade in session-start-autofix.sh. Removing it after
integration completes prevents stale-flag warnings at future session starts.

## Rules
- Do this proactively. Don't wait for the user to ask "did you update the routing?"
- Both CLAUDE.md files (global + project) must stay in sync.
- If a promote step fails, diagnose the mechanism rather than retrying blindly.

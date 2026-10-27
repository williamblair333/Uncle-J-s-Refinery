




<!-- UNCLE-J-GEMINI-START -->
## Uncle J's Refinery Integration (Passive Observer)

**Mandate:** You are operating in a workspace managed by Uncle J's Refinery. To maintain functional parity with Claude Code while ensuring zero operational interference, you MUST adhere to the following rules:

1.  **Passive Observation**: NEVER modify `~/.claude/settings.json` or the Refinery's internal `state/` files. Your integration is strictly read-only regarding Claude's state.
2.  **Structural Exploration**: Use the Refinery's retrieval stack instead of your standard `grep_search` or `read_file` tools. The stack's MCP servers are registered for Antigravity (`features/antigravity/sync_mcp.py`) and the routing policy is loaded globally from `~/.gemini/GEMINI.md`.
    - **Code**: call the `jcodemunch` MCP tools (`resolve_repo`, `search_symbols`, `get_symbol_source`, ...).
    - **Memory**: call the `memweave` MCP tool `memory_search` before proposing architectural changes.
    In headless jobs (`agy -p`, `ask_agy`) skip the commands in rules 3 and 6: they are not on the allow list, and a denied command ends the job.
3.  **Context Synchronization** (interactive sessions only): At the start of any complex task (research, refactoring, or bug fixing), run the startup probe to synchronize with the latest repository changes and AI playbooks:
    - `bash /opt/proj/Uncle-J-s-Refinery/features/gemini-integration/startup-probe.sh`
4.  **Research First**: Before proposing a new solution or starting a substantive task, you MUST search the internet (via search tools) to ensure a solution does not already exist and to stay current with the latest technical standards and library updates. Do NOT reinvent the wheel.
5.  **Output Discipline**: Adopt the `jOutputMunch` format. Provide high-signal technical responses. Eliminate conversational filler, preambles, and summaries unless specifically requested.
6.  **Validation** (interactive sessions only): Before concluding any task, verify your changes by running:
    - `bash /opt/proj/Uncle-J-s-Refinery/healthcheck.sh --quick`
<!-- UNCLE-J-GEMINI-END -->

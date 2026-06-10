

<!-- UNCLE-J-GEMINI-START -->
## Uncle J's Refinery Integration (Passive Observer)

**Mandate:** You are operating in a workspace managed by Uncle J's Refinery. To maintain functional parity with Claude Code while ensuring zero operational interference, you MUST adhere to the following rules:

1.  **Passive Observation**: NEVER modify `~/.claude/settings.json` or the Refinery's internal `state/` files. Your integration is strictly read-only regarding Claude's state.
2.  **Structural Exploration**: Use the Refinery's retrieval stack instead of your standard `grep_search` or `read_file` tools.
    - **Code**: Use `/opt/proj/Uncle-J-s-Refinery/.venv/bin/jcodemunch-mcp` via `run_shell_command`.
    - **Memory**: Use `/opt/proj/Uncle-J-s-Refinery/.venv/bin/mempalace search` via `run_shell_command` before proposing architectural changes.
3.  **Context Synchronization**: At the start of any complex task (research, refactoring, or bug fixing), run the startup probe to synchronize with the latest repository changes and AI playbooks:
    - `bash /opt/proj/Uncle-J-s-Refinery/features/gemini-integration/startup-probe.sh`
4.  **Research First**: Before proposing a new solution or starting a substantive task, you MUST search the internet (via search tools) to ensure a solution does not already exist and to stay current with the latest technical standards and library updates. Do NOT reinvent the wheel.
5.  **Output Discipline**: Adopt the `jOutputMunch` format. Provide high-signal technical responses. Eliminate conversational filler, preambles, and summaries unless specifically requested.
6.  **Auto-Skill**: You are equipped with the `gemini-auto-skill`. You MUST monitor your sessions for reusable workflows and draft native Gemini skills into `.gemini/skills/` when you identify a repeatable pattern that would benefit from automation.
7.  **Validation**: Before concluding any task, verify your changes by running:
    - `bash /opt/proj/Uncle-J-s-Refinery/healthcheck.sh --quick`
<!-- UNCLE-J-GEMINI-END -->

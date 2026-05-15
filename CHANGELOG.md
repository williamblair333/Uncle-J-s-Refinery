# CHANGELOG — Uncle J's Refinery

---

## 2026-05-15 — MemPalace HNSW corruption fix + mine concurrency lockfiles

### Fixes

- **MemPalace HNSW index corruption** — `link_lists.bin` in the `mempalace_drawers` HNSW segment grew to 145 GB (corrupted write, root cause unknown). Every subsequent `mempalace mine` call and MCP server start crashed with SIGSEGV (exit 139). Deleted the five corrupt HNSW files individually; chromadb rebuilt the index automatically from the SQLite `embeddings` table. All 7,660 drawers intact. New index: 3.2 MB total, `link_lists.bin` 16 KB.
- **Duplicate mine processes on session end** — Two Stop hooks fired the convos miner concurrently on every session end: a direct `mempalace mine` command in `.claude/settings.json` (project-level) and `mempalace-mine-convos.sh` in `~/.claude/settings.json` (global). This spawned 3–4 concurrent Python processes (~400 MB RSS each) and exhausted swap on a 14 GB machine.
- **`scripts/mempalace-mine-convos.sh`** — Added `mkdir`-based lockfile (`state/mempalace-mine-convos.lock`). Concurrent invocations log "skipped: already running" and exit 0. Lock released via `trap … EXIT`.
- **`scripts/mempalace-mine-project.sh`** — Same lockfile pattern (`state/mempalace-mine-project.lock`).
- **`.claude/settings.json`** — Replaced direct `mempalace mine … < /dev/null` Stop hook with `bash scripts/mempalace-mine-convos.sh` so all invocations go through the lockfile-guarded wrapper.

### Root cause note

`mempalace mine` has no built-in concurrency guard. Lockfiles in the wrappers are the correct layer until upstream ships a fix. If MemPalace is upgraded, re-test concurrent invocation behaviour.

---

## 2026-05-14 — Dreaming, Outcomes, Multi-agent & Session Stats

### Features

- **`features/dreaming/dream.sh`** — Scheduled batch (2 AM daily) that queries Langfuse traces, invokes the `dream-synthesizer` skill, and writes recurring-mistake patterns and proven playbooks to MemPalace (`wing: dreaming`) and `~/.claude/CLAUDE.md`. `/dream` slash command for on-demand runs.
- **`features/dreaming/skills/dream-synthesizer/SKILL.md`** — Skill that structures Langfuse traces into `## Recurring Mistakes` / `## Proven Playbooks` output.
- **`features/dreaming/install.sh`** — Registers 2 AM daily cron (`DREAMING_CRON_SCHEDULE`), installs `/dream` command.
- **`global-skills/outcomes/SKILL.md`** — Rubric-aware grader that runs in a fresh context window; returns a JSON verdict (`pass`/`fail`) with per-criterion remediation steps.
- **`global-skills/outcomes/RUBRIC.md.template`** — Six-criterion starter rubric for new projects.
- **`global-skills/orchestrator/SKILL.md`** — Decomposes a PRD into a JSON task manifest (`role`, `task` pairs) for parallel sub-agent execution.
- **`ralph-harness.sh --rubric`** — Invokes outcomes grader after each done-gate; injects gap report as next-iteration context; exits only when both structural gate and rubric pass. Cap: `OUTCOMES_MAX_ITERATIONS` (default 5).
- **`ralph-harness.sh --decompose`** — Orchestrator decomposes PRD → parallel `claude -p` sub-agents with `AGENT_ROLE` env → synthesis agent merges outputs and updates PRD `## Progress` section → outcomes grader.
- **`features/session-stats/stats.sh`** — Weekly efficiency reporter: queries Langfuse last N days, groups by date + project, renders markdown table with token-use flag (`⚠ high` > 40k). `/stats` slash command. `--cron` writes to `~/.claude/dreaming-output/stats-YYYY-MM-DD.md` (picked up by dreaming) and `state/stats-weekly.md`.
- **`features/session-stats/install.sh`** — Registers Sunday 8 AM cron (`STATS_CRON_SCHEDULE`), installs `/stats` command.
- **`~/.claude/hooks/langfuse_hook.py`** — AGENT_ROLE tag added to Langfuse traces (both `tags` list and `update_current_trace` metadata) so multi-agent runs appear as a role-tagged tree.
- **`prd-template.md`** — Added `## Success Rubric` and `## Agent Decomposition` sections.

### Fixes

- **`install-reliability.sh`**: skill loop read `skills/` not `global-skills/` — skills never installed on fresh runs. Fixed path; expanded loop to include `outcomes`, `orchestrator`, `per-task-review-cycle`, `post-upgrade-mcp-integration`.
- **`install-reliability.sh`**: now writes `OUTCOMES_MAX_ITERATIONS=5` to `~/.claude/settings.json` env block on install so fresh installs don't require manual intervention.
- **`install-langfuse.sh`**: Stop hook registration used `d["hooks"]["Stop"] = [...]` assignment, destroying all other Stop hooks on re-install. Fixed to idempotent prepend using `"langfuse_hook.py"` as marker.
- **`install-langfuse.sh`**: AGENT_ROLE patch extended to also convert the inline `metadata={}` dict in `update_current_trace` to a `trace_metadata` variable with conditional `agent_role` key (previously only the tags list was patched).
- **`ralph-harness.sh`**: `OUTCOMES_CONTEXT` not cleared after `build_inner_prompt()` subshell call — stale gap context leaked into the wrong iteration. Explicit clear added in parent after call.
- **`ralph-harness.sh`**: `OUTCOMES_CONTEXT` not cleared on successful `--decompose` path. Fixed.
- **`ralph-harness.sh`**: `decompose_dir` had no trap on RETURN — temp dir leaked on error exit. `trap 'rm -rf "$decompose_dir"' RETURN` added.
- **`ralph-harness.sh`**: `--decompose` fallback path (empty manifest) did not inject `$PRE_OUTPUT` into the prompt. Fixed to match the normal single-agent branch.
- **`ralph-harness.sh`**: `decompose_output` (synthesis agent result) was captured but silently discarded. Now printed to stdout.
- **`ralph-harness.sh`**: Synthesis agent now receives PRD path and task manifest; instructed to update `## Progress` and write `DONE` when all tasks complete — so `invoke_done_gate` and `invoke_outcomes_check` get accurate PRD state after each decompose iteration.
- **`features/session-stats/stats.sh`**: `printf '%s' "$TRACES_JSON" | python <<'PYEOF'` — heredoc wins over pipe for subprocess stdin, data silently dropped, report always empty. Fixed with `TRACES_JSON="$var" python <<'PYEOF'` + `os.environ["TRACES_JSON"]`.
- **`verify.sh`**: sources `state/dreaming.env` before dreaming checks so `DREAMING_ENABLED` is read from the installed env file without requiring manual export. Added session-stats cron check. Global-skills check now covers all four `install-reliability.sh`-managed skills.
- **`healthcheck.sh`**: added session-stats cron registration check and `per-task-review-cycle` / `post-upgrade-mcp-integration` to skills loop.

### Docs

- `docs/STACK.md`: added Dreaming, Orchestrator + Multi-agent, and Session Stats sections.
- `docs/RELIABILITY.md`: added outcomes grader row to component table; documented `OUTCOMES_MAX_ITERATIONS` configuration.
- `features/dreaming/README.md`: created.
- `features/session-stats/README.md`: created.

---

## 2026-04-23 — Hermes: Autonomous Loop & Skill Automation

### Features

- **`scripts/skill-suggest.sh`** — Claude Code Stop hook that reads the session transcript after every session, calls `claude --print` to evaluate whether the session demonstrated a reusable workflow, and auto-drafts a Markdown skill file to `~/.claude/skills/drafts/` if so. Sends a Telegram preview of the draft.
- **`features/auto-skill/install.sh`** — Registers `skill-suggest.sh` as a Stop hook in `.claude/settings.json`. Supports `--uninstall`. Idempotent.
- **`scripts/ralph-cron-run.sh`** — Cron-safe wrapper for `ralph-harness.sh`. Reads configuration from env vars (`RALPH_PRD`, `RALPH_MAX_ITER`, etc.), logs to `state/ralph-cron.log`, and sends Telegram notifications on start, completion, max-iterations-hit, and failure.
- **`features/ralph-cron/install.sh`** — Interactive installer for Ralph cron jobs. Prompts for PRD path, cron schedule, risk threshold, max iterations, skip-judge, and dry-run. Generates a unique marker per PRD. Supports `--list` and `--uninstall MARKER`. Sends Telegram confirmation on install.

### Fixes

- `skill-suggest.sh`: added `trap 'exit 0' ERR` to guarantee exit-0 contract for Stop hooks under `set -euo pipefail`
- `skill-suggest.sh`: removed duplicate `--print` flag alongside `-p`
- `ralph-cron/install.sh`: inject `PATH` and `CLAUDE_BIN` into generated cron entries so `claude` is found at runtime (mirrors `telegram-gateway/install.sh` pattern)
- `ralph-cron/install.sh`: single-quote all path values in cron entry string to handle paths with spaces
- `ralph-cron/install.sh`: strip both leading and trailing dashes from PRD slug

---

## 2026-04-22 — Hermes: Telegram Integration Pipeline

### Features

- **`scripts/session-notify.sh`** — Claude Code Stop hook that sends a Telegram summary of the last assistant message when a session ends. Extracts `session_id` and `transcript_path` from the hook JSON payload.
- **`features/telegram-notify/install.sh`** — Registers `session-notify.sh` as a Stop hook. Validates `.env` credentials, sends test message on install. Supports `--uninstall`.
- **`scripts/telegram-gateway-poll.sh`** — Cron job (every 2 min) that polls Telegram for incoming messages, runs them through `claude --print` in the repo context, and replies. Message text passed as subprocess argument (no shell injection). Offset-tracked via `state/telegram-gateway-offset.txt`.
- **`features/telegram-gateway/install.sh`** — Installs the gateway poll cron job. Validates bot token via `getMe`, discovers `claude` binary path, injects `PATH` and `CLAUDE_BIN` into the cron entry. Supports `--uninstall`.
- **`lib/notify.sh`** — Channel abstraction for notifications. Dispatches `notify_send_text`, `notify_send_pitch`, `notify_poll_reply` to the configured backend (default: Telegram).
- **`lib/feature-helpers.sh`** — Shared installer utilities: `install_cron`, `remove_cron`, `prompt_yes_no`, `prompt_value`, `write_env_var`.
- **`scripts/stack-alerts-send.sh`** — Daily changelog analysis script that calls `claude --print` to generate a stack-upgrade pitch and sends it to Telegram.
- **`scripts/stack-alerts-poll.sh`** — 2-minute cron poller that checks for stack upgrade callbacks and invokes the upgrade invoker.
- **`features/stack-alerts/install.sh`** — Interactive Linux setup: configures Telegram credentials in `.env`, installs `stack-alerts-send` as a daily cron and `stack-alerts-poll` as a 2-minute cron.

### Chore

- Scaffolded `lib/`, `features/stack-alerts/`, `state/` directories for the alert pipeline

---

## 2026-04-21 — Core Harness, Hooks & Cross-Platform Parity

### Features

- **`ralph-harness.sh`** — Autonomous verification-gated loop: runs `claude` iterations against a PRD, calls `get_changed_symbols` / `get_untested_symbols` / `get_pr_risk_profile` between iterations via a done-gate, exits only when risk < threshold, untested = 0, and PRD is marked DONE. Hard iteration cap.
- **`healthcheck.sh`** — Runtime healthcheck with SessionStart trigger and `/health` slash command automation. Verifies stack components are live.
- Auto-checkpoint hook on Write/Edit (commits with `chk: HH:MM:SS` on every file change)
- MCP tool call logger hook

### Fixes

- `ralph-harness`: fixed `--cwd` regression; pass `--dangerously-skip-permissions` to done-gate
- `ralph-harness`: ignore installer transcripts in `.gitignore`
- Healthcheck: fixed check #9 flake by invoking Stop hook directly
- MCP regressions: force-rebind, set `MCP_TIMEOUT`, mark scripts `+x`
- Install scripts: clear all MCP scopes on re-run, preserve venv extras
- `verify.sh`: prepend `~/.local/bin` to PATH; add `git --version` check
- `install-guardrails.sh`: pass variant as positional argument
- Disabled Serena dashboard browser auto-open by default

### Docs

- `README.md`: updated with PRD for Ralph-driven maintenance
- `HANDOFF.md`: overnight briefing added
- Overnight work log appended
- MCP client configs templatized for cross-platform install
- `MIT LICENSE` added

---

## 2026-04-20 — Foundation

- **Initial commit**: Uncle J's Refinery project scaffolded
- jcodemunch-mcp hook paths auto-patched to full binary in installers
- Commercial-use terms clarified for upstream components
- `install-langfuse.sh` hardened for Linux / cgroup-v2 hosts

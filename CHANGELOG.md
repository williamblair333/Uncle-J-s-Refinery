# CHANGELOG — Uncle J's Refinery

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

- **`ralph-harness.sh`** — Bash port of `ralph-harness.ps1`. Autonomous verification-gated loop: runs `claude` iterations against a PRD, calls `get_changed_symbols` / `get_untested_symbols` / `get_pr_risk_profile` between iterations via a done-gate, exits only when risk < threshold, untested = 0, and PRD is marked DONE. Hard iteration cap.
- **`healthcheck.sh`** — Runtime healthcheck with SessionStart trigger and `/health` slash command automation. Verifies stack components are live.
- Auto-checkpoint hook on Write/Edit (commits with `chk: HH:MM:SS` on every file change)
- MCP tool call logger hook

### Fixes

- `ralph-harness`: fixed `--cwd` regression; pass `--dangerously-skip-permissions` to done-gate
- `ralph-harness`: ignore installer transcripts in `.gitignore`
- Healthcheck: fixed check #9 flake by invoking Stop hook directly
- MCP regressions: force-rebind, set `MCP_TIMEOUT`, mark scripts `+x`
- Install scripts: clear all MCP scopes on re-run, preserve venv extras
- `verify.sh`: prepend `~/.local/bin` to PATH; add `git --version` check (parity with `verify.ps1`)
- `prerequisites.ps1`: add Docker check (parity with `prerequisites.sh`)
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

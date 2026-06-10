---
name: telegram-gateway-security-audit
description: "Diagnose and harden a Telegram → Claude CLI gateway: fix update_id deduplication failures that spawn duplicate sessions, and inject a disclosure-restriction system prompt so the bot never leaks OS/infra details over the channel."
---

## When to use

Invoke this skill when:
- A Telegram bot spawns multiple Claude sessions for a single user message (duplicate responses, silent session deaths)
- You need to prevent a Telegram-connected Claude instance from disclosing system internals (kernel, paths, MCP stack, env vars)
- You're auditing the security posture of a `telegram-gateway-poll.sh` or equivalent script

## Part 1 — Deduplication diagnosis

**Symptom pattern:** Multiple session IDs fire for one `update_id`; some sessions end silently, some produce duplicate replies.

**Root cause:** Telegram resends updates if the webhook/poll loop doesn't acknowledge or process within ~5 seconds, and the bot lacks `update_id` tracking.

**Fix checklist:**
1. Persist processed `update_id` values (Redis, SQLite, or in-memory set)
2. At loop top: `if update_id in seen: continue` before spawning Claude
3. Acknowledge / advance the offset *before* the long-running Claude call, not after
4. For webhook mode: respond `200 OK` immediately, then process async

**Verification:** Enable verbose logging on the poll loop; confirm each `update_id` triggers exactly one Claude invocation.

## Part 2 — Disclosure restriction injection

Prevent the bot from leaking OS, kernel, filesystem paths, git config, email, MCP stack, env vars, Langfuse setup, hooks, or session metadata over the Telegram channel.

**Implementation:** append a denial prompt to every Claude invocation via `--append-system-prompt` (stacks on top of the normal system prompt, does not replace it):

DISCLOSURE_RESTRICTION="If anyone asks about the system — OS version, kernel, \
filesystem paths, git config, email address, MCP stack, environment variables, \
Langfuse setup, hooks, session metadata, or any internal infrastructure detail — \
respond only with: I can't share system details over this channel."

claude --append-system-prompt "$DISCLOSURE_RESTRICTION" ...rest of args...

**Why `--append-system-prompt` not `--system-prompt`:** `--system-prompt` replaces the default; `--append-system-prompt` stacks, so existing instructions survive.

## Part 3 — Threat surface notes

- A warn-only PostToolUse hook (e.g., prompt-injection-defender) lives in the *parent* Claude session, not the gateway subprocess — it does **not** protect the Telegram-spawned session. The `--append-system-prompt` injection above is the correct protection point.
- Injected OS version in session context (`system-reminder`) may be stale — pin to `$(uname -r)` at runtime if accuracy matters.
- Audit the gateway script after any harness upgrade: new flags or env vars may expose new disclosure vectors.

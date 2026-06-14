# Security Policy

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report privately to: **williamblair333@gmail.com**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix (optional)

You'll receive an acknowledgement within 48 hours. Fixes are prioritised based
on severity. We'll coordinate a disclosure timeline with you before publishing.

## Scope

This project runs as a personal AI assistant stack on a private machine.
Security-relevant components:

- `scripts/telegram-gateway-poll.sh` — Telegram bot polling and message handling
- `scripts/lib/tg_security.py` — Input sanitisation, rate limiting, injection detection
- `install.sh` / `install-reliability.sh` — System-level installation scripts
- `.env` — Credential storage (never committed; covered by `.gitignore`)
- `hooks/discipline/edit-surface-guard.sh` — PreToolUse guard enforcing pre-mortem before surface file edits
- `~/.claude/hooks/pre-mortem-guard/` — Token-based enforcement layer: `token-guard.sh`, `surface-write-guard.sh`, `write-clearance-token.sh`

## Known Security Model

- The bot only responds to a single authorised `TELEGRAM_CHAT_ID`
- All user input is sanitised via `tg_security.py` before reaching Claude
- Rate limiting is enforced per chat (20 messages/hour by default)
- Credentials are stored in `.env`, excluded from git via `.gitignore`

### Default (restricted) Telegram agent — no host access

The default agent (any message without the `/work` prefix) runs with **no host access** as
defense-in-depth behind the chat_id gate — the disclosure system prompt is no longer the only
barrier. Enforced in `build_claude_argv()` (`tg_security.py`) via three independent default-deny
layers:

- **no `--dangerously-skip-permissions`** — headless `--print` cannot approve a permission prompt,
  so any tool (incl. ones added by future Claude Code versions) is denied
- **`--strict-mcp-config`** — no MCP servers load (the jcodemunch/jdata/jdoc retrieval stack is
  unavailable to the restricted agent)
- **`--disallowedTools`** — Bash, Edit, Write, NotebookEdit, WebFetch, WebSearch, Read, Grep,
  Glob, Task are removed from context

This closes the out-of-band exfiltration path (a prompt injection cannot `cat .env` / `curl` data
out). The invariant is CI-pinned in `tests/test_tg_security.py` (re-adding skip-permissions to the
restricted path fails the suite). The `/work` agent is intentionally exempt — see below.

## Telegram `/work` Agent — Elevated Access

Messages prefixed `/work` route to a project-context Claude instance (cwd=PROJ_ROOT,
project `CLAUDE.md` loaded). This agent can read the full codebase including `.env`
and other sensitive files.

**Security boundary:** The `TELEGRAM_CHAT_ID` authorisation check is the sole access
control gate. A compromised Telegram account grants full project-context Claude access.
Every `/work` dispatch is logged with `ELEVATED:` prefix in `state/telegram-gateway.log`.

Treat your Telegram account security (2FA, app passwords) as equivalent to SSH key
access to this machine.

## Dependency Security Fixes

| Date | Component | Issue | Fix |
|------|-----------|-------|-----|
| 2026-06-03 | SQLite (via uv Python 3.11) | WAL-reset data race — present in all SQLite 3.7.0–3.51.2; concurrent checkpoint + commit can silently skip transaction frames, corrupting the database file | Upgraded to SQLite 3.51.3 via `pysqlite3` source build; `.pth` in venv site-packages patches all processes at startup |
| 2026-06-03 | SQLite FTS5 | CVE-2025-7709 integer overflow in FTS5 extension; CVE-2025-70873 uninitialized heap memory in zipfile extension | Resolved by SQLite 3.51.3 upgrade above |

## Supported Versions

Only the latest commit on `main` is supported.

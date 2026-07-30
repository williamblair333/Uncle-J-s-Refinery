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

### Rate-limit locking is best-effort on Windows (2026-07-30)

`check_rate_limit` serialises reads/writes of its JSON state file with an
exclusive file lock. `fcntl.flock` is POSIX-only, so the Windows port selects
`msvcrt.locking` instead. Two behavioural differences matter:

- `msvcrt.locking` **gives up after ~10 s**, where `flock` blocks indefinitely.
- On failure the helper returns `False` and the caller **proceeds without the
  lock** rather than raising — deliberate, matching the surrounding fail-open
  design (a lock we cannot take must not block a legitimate message).

Consequence: under heavy concurrent delivery on Windows, two workers could
interleave a read-modify-write and undercount, letting a chat exceed 20
messages/hour. The chat_id gate and input sanitisation are unaffected — this
weakens throttling only, not authorisation. The gateway is single-consumer per
token (`getUpdates`), so concurrency here should be rare in practice.

If strict throttling on Windows is ever required, move the counter to a SQLite
table with a transaction rather than a JSON file plus an advisory lock.

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

### Skill promotion (`promote`) hardening

Promoting a Telegram skill draft installs it into `~/.claude/skills` (global, all sessions), so the
`promote` path is a supply-chain surface. Controls (`tg_security.py`):

- **Whole-file injection scan** — `scan_skill_body` scans the entire draft, **frontmatter included**.
  A skill's `description:` is loaded by Claude in future sessions, so an injection hidden there is a
  persistent cross-session vector; body-only scanning (the prior behavior) let it through.
- **No destructive overwrite** — `assert_skill_target_safe` refuses to install over a real
  (non-symlink) skill on a name collision; only a gateway-owned symlink is replaced. The previous
  `shutil.rmtree` path could delete a legitimate skill.

### Output redaction (defense-in-depth)

`scan_output` redacts secrets/paths from replies (API keys incl. spaced `sk - ant -`, relative
`.env` paths, emails, host paths, IPs). This is **defense-in-depth, not a primary control** — the
real protection is the restricted agent's removed action channel (above). Prose-spelled keys
("es kay dash ant…") are an accepted residual; denylist redaction is inherently lossy.

### getUpdates single-consumer (reliability invariant)

The gateway is the **sole** `getUpdates` consumer (Telegram is single-consumer-per-token). A second
no-offset consumer corrupted the shared offset for 22 days, freezing the bot and re-skipping a stale
backlog (the message-flood incident). Stack-alert approvals route through the gateway via a state
file, not a second `getUpdates` call. Re-introducing a second consumer is a regression.

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

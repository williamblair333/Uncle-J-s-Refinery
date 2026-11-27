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

This project runs a personal AI assistant on a private machine. The following
components handle messages, credentials, or other security-sensitive work.

- `scripts/telegram-gateway-poll.sh` — Checks Telegram for new messages and handles them
- `scripts/lib/tg_security.py` — Cleans up input, limits how often a chat can send messages, and looks for attempts to slip instructions into input
- `install.sh` / `install-reliability.sh` — Install components system-wide on the machine
- `.env` — Stores credentials. Never commit it; `.gitignore` excludes it.
- `hooks/discipline/edit-surface-guard.sh` — Runs before tool calls and requires a pre-mortem (a review of what could go wrong) before edits to surface files (scripts, config files, systemd units, the justfile, `CLAUDE.md`, and anything under `hooks/`, `scripts/` or `features/`; test modules under `tests/` are exempt)
- `hooks/discipline/credential-guard.sh` — PreToolUse guard (runs before every tool call; matcher `*`): denies any call touching credential or system secret files, read-only included. Wired as `… || exit 1`, so a broken guard fails open, never locks tools out. Text matching, so obfuscated paths get through; not a sandbox
- `scripts/live_preview/` — serves build images on 127.0.0.1 only. Host-header check (DNS rebinding), image-only inputs copied through one `O_NOFOLLOW` fd, generated stored filenames (the vendored page doesn't escape them), `~/.live-preview` at 0700
- `~/.claude/hooks/pre-mortem-guard/` — Enforces the pre-mortem with a clearance-token file (a marker the pre-mortem skill writes when it passes), through `token-guard.sh`, `surface-write-guard.sh`, and `write-clearance-token.sh`
- `scripts/jdocmunch-reindex.sh` — `LOCAL_ONLY_REPOS` allowlist forcing summaries/embeddings off for personal-context doc corpora
- `~/.config/systemd/user/jdocmunch-watch.service.d/override.conf` — drop-in pinning the doc watcher's indexing posture (survives `watch-install`)

## Known Security Model

- The bot only responds to a single authorised `TELEGRAM_CHAT_ID`
- All user input is sanitised via `tg_security.py` before reaching Claude
- Rate limiting is enforced per chat (20 messages/hour by default)
- Credentials are stored in `.env`, excluded from git via `.gitignore`

### Rate-limit locking is best-effort on Windows (2026-07-30)

`check_rate_limit` uses an exclusive lock so only one worker at a time can
read and update the JSON state file. On POSIX systems such as Linux, it uses
`fcntl.flock`. On Windows, it uses `msvcrt.locking`. The Windows lock can time
out, which affects how strictly the gateway can limit messages.

- `msvcrt.locking` **gives up after ~10 s**. `flock` waits indefinitely.
- If the helper cannot get the lock, it returns `False`. The caller **proceeds
  without the lock** instead of raising an error. This is deliberate: like the
  rest of the gateway, it fails open, so a lock it cannot take never blocks a
  legitimate message.

If two Windows workers read the same count and write their updates at the same
time, one update could overwrite the other. A chat could then exceed 20
messages/hour. The chat ID check and input cleaning still apply. This weakens
only the message limit, not the check on who may send. The gateway uses one
`getUpdates` consumer per token, so two workers updating the counter at once
should be rare in practice.

If strict throttling on Windows is ever required, move the counter to a SQLite
table with a transaction rather than a JSON file plus an advisory lock.

### Default (restricted) Telegram agent — no host access

The default agent handles messages without the `/work` prefix. It runs with **no
host access**. This adds a layer of protection behind the chat ID check, so the
prompt that tells the agent what it may disclose is no longer the only barrier.
Three independent controls in `build_claude_argv()` (`tg_security.py`) deny
access by default; each holds even if the others fail.

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

A skill gives Claude reusable instructions. Promoting a Telegram skill draft
installs it in `~/.claude/skills`, where Claude can use it in any session.
Because a draft can affect future sessions, `promote` applies the following
checks in `tg_security.py`.

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

Only the gateway calls `getUpdates` to fetch messages for its Telegram token.
Telegram allows only one reader per bot token. An offset tells Telegram where to
resume. A second reader that omitted the offset corrupted the shared position
for 22 days. The bot froze and repeatedly skipped old messages. This was the
message-flood incident. Stack-alert approvals go through the gateway's state
file, not a second `getUpdates` call. Adding a second reader is a regression.

### Local-only doc corpora — no remote egress from indexing (2026-08-15)

Keep personal document collections on the machine when indexing them for search.
Their contents must never go to a remote service for summarising or making
embeddings (numeric representations used to find related text). For example: the
Obsidian vault of personal notes, which deliberately has no git remote, and the
frozen archive of migrated memory.

`jdocmunch` defaults to `use_ai_summaries=True` and `use_embeddings="auto"` when
it runs `index_local`. Both will use whatever provider the environment offers,
with **no log line and no prompt**. Because of that, the project forces
local-only settings explicitly in three independent places:

- **Cron path** — `LOCAL_ONLY_REPOS` in `scripts/jdocmunch-reindex.sh` is an allowlist (deliberately
  not a global default — flipping it would silently change behaviour for every other doc repo). A
  listed corpus is indexed with `use_ai_summaries=False` **and** `use_embeddings=False`.
- **Fallback path** — `run_index_local()`'s CLI fallback, used when the Python API is unavailable,
  carries the same `--no-ai-summaries --embeddings off` plus the repo's exclusions. A guarantee that
  holds only on the happy path is not a guarantee.
- **Watcher path** — the watcher's `--no-ai-summaries` lives in a systemd drop-in
  (`jdocmunch-watch.service.d/override.conf`), **not** in the unit file:
  `service_installer.py::_install_systemd()` rewrites the unit on every `watch-install` and
  `_exec_cmd()` hardcodes the argv, so a hand-edited `ExecStart` is silently reverted by the next
  stack upgrade. Drop-ins are never touched. Verifying the control means reading
  `~/.doc-index/logs/watch.err` for tracebacks — `systemctl is-active` is **not** a health check
  here, because the watcher's internal retry loop reports `active/running` with `NRestarts=0` while
  failing every rediscover cycle.

Two things to know before changing any of this:

- **File exclusions persist; the summarizer flag does not.** `extra_ignore_patterns` are stored in
  the manifest as `corpus_shape_patterns` and inherited by any later refresh that omits them — which
  is what makes the watcher (it passes no patterns) safe. `use_ai_summaries` has no such
  persistence, which is exactly why it must be re-asserted at every call site above.
- **Indexing copies file contents.** `index_local` writes a copy under
  `~/.doc-index/local/<repo>/`. If a file contains a secret, the copy puts that
  secret outside the original repo. Exclude sensitive files before the first
  run. If they are already indexed, delete the index and rebuild it with those
  files excluded. Editing the source leaves the indexed copy in place.

**Residual — narrower than first written; corrected 2026-08-16 against upstream source.**
`jdocmunch-mcp watch` exposes no embeddings flag (unlike `index-local`, which gained
`--embeddings` / `--no-embeddings` in upstream #108), and `_systemd_env_lines()` forwards every
`JDOCMUNCH_*` variable into the unit. So a user who has **deliberately** enabled a provider has
no way to turn embeddings off on the watcher path specifically.

An earlier version of this section claimed that setting `JDOCMUNCH_OPENAI_COMPAT_URL` alone
turned `use_embeddings="auto"` ON for every watched repo. **That was wrong.** Verified against
upstream `9235e228` (= our pinned version): `_EMBED_AUTO_DETECT_ORDER` in
`embeddings/provider.py` contains only `GOOGLE_API_KEY → gemini` and `OPENAI_API_KEY → openai`,
both suppressed unless `JDOCMUNCH_ALLOW_PAID_EMBEDDINGS` is set, and `openai-compatible` is
**never** auto-selected — it requires naming `JDOCMUNCH_EMBEDDING_PROVIDER=openai-compatible`
plus both a URL and a model. Upstream added that opt-in gate in v1.127.0 (2026-08-09), six days
before we wrote the claim, so this was our error, not an upstream regression.

Enabling embeddings for a watched local-only corpus therefore takes a deliberate multi-part
opt-in, not one ambient variable. Still revisit the drop-in before setting any of them.
Upstream flag passthrough is tracked in ROADMAP as
[jgravelle/jdocmunch-mcp#120](https://github.com/jgravelle/jdocmunch-mcp/issues/120).

**Do not remove the drop-in as cleanup.** It is retired only once `systemctl --user show
jdocmunch-watch.service -p ExecStart` shows the flag coming from the unit itself — i.e. after
upstream passthrough lands *and* a `watch-install` has been re-run and verified. Deleting it on
the strength of an upstream release note alone silently restores `use_ai_summaries=True`, and
nothing logs that it happened.

## Telegram `/work` Agent — Elevated Access

Messages that start with `/work` go to a Claude agent running in the project root
(cwd=PROJ_ROOT). It loads the project's `CLAUDE.md` and can read the entire
codebase, including `.env` and other sensitive files.

The `TELEGRAM_CHAT_ID` check is the only access control. Anyone who takes over
the authorised Telegram account gains the same project access as this agent.
The gateway logs every `/work` request with the prefix `ELEVATED:` in
`state/telegram-gateway.log`.

Guard your Telegram account's security (2FA, app passwords) as carefully as an SSH key to this machine.

## Dependency Security Fixes

| Date | Component | Issue | Fix |
|------|-----------|-------|-----|
| 2026-06-03 | SQLite (via uv Python 3.11) | WAL-reset data race — present in all SQLite 3.7.0–3.51.2; concurrent checkpoint + commit can silently skip transaction frames, corrupting the database file | Upgraded to SQLite 3.51.3 via `pysqlite3` source build; `.pth` in venv site-packages patches all processes at startup |
| 2026-06-03 | SQLite FTS5 | CVE-2025-7709 integer overflow in FTS5 extension; CVE-2025-70873 uninitialized heap memory in zipfile extension | Resolved by SQLite 3.51.3 upgrade above |

## Supported Versions

Only the latest commit on `main` is supported.

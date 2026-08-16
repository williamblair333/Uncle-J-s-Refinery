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
- `scripts/jdocmunch-reindex.sh` — `LOCAL_ONLY_REPOS` allowlist forcing summaries/embeddings off for personal-context doc corpora
- `~/.config/systemd/user/jdocmunch-watch.service.d/override.conf` — drop-in pinning the doc watcher's indexing posture (survives `watch-install`)

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

### Local-only doc corpora — no remote egress from indexing (2026-08-15)

Some indexed doc corpora are personal-context and must never reach a remote summarizer or an
embeddings endpoint — notably a deliberately remote-less Obsidian vault holding personal notes
and a frozen archive of migrated memory.

`jdocmunch`'s `index_local` defaults are `use_ai_summaries=True` and `use_embeddings="auto"`, and
both reach for whatever provider the environment exposes with **no log line and no prompt**. The
posture is therefore forced explicitly, at three independent call sites:

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

Two properties worth knowing before changing any of it:

- **File exclusions persist; the summarizer flag does not.** `extra_ignore_patterns` are stored in
  the manifest as `corpus_shape_patterns` and inherited by any later refresh that omits them — which
  is what makes the watcher (it passes no patterns) safe. `use_ai_summaries` has no such
  persistence, which is exactly why it must be re-asserted at every call site above.
- **Indexing duplicates bytes.** `index_local` copies file contents into a raw mirror under
  `~/.doc-index/local/<repo>/`, so indexing a secret-bearing corpus copies the secret into a store
  outside that corpus's own repo. Exclude before the first index, or delete the index and rebuild —
  editing the source afterwards does not reach the mirror.

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

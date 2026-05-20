# Uncle J's Refinery

*Industrial-grade context hygiene for Claude Code.*

Uncle J's Refinery is a self-hosted, locally-installed stack that turns a
Claude Code agent into a precision instrument. Crude tokens in, refined
work out. Input tokens down ~80% via structural retrieval — code, data,
docs, memory. Output tokens down ~25-40% via prompt-level discipline.
Every turn traced to a local Langfuse. Every destructive command gated.
Every edit verified before it lands. Twelve components, one install.

**Linux/macOS.** Built and tested on Debian/Ubuntu. macOS works without
modification.

## The "Uncle J" is J. Gravelle

This whole project is named in tribute to **J. Gravelle**
([@jgravelle](https://github.com/jgravelle)), creator of the four
tools that put the *refinery* in Uncle J's Refinery:

- **jCodeMunch** — symbol-level code retrieval (~95% token reduction on
  code-reading workflows)
- **jDataMunch** — CSV/tabular retrieval (~25,000x reduction on the
  LAPD 1M-row benchmark)
- **jDocMunch** — section-precise documentation retrieval
- **jOutputMunch** — prompt-level rules that cut output tokens 25-40%

Those four pieces — three for input, one for output — do the actual
distillation. Everything else in this repo (MemPalace, Serena,
Context7, DuckDB, Superpowers, Ralph, guardrails, Langfuse, custom
skills, install/verify scripts) is plumbing and governance built
around the j*Munch core. Without J. Gravelle's work, there is no
refinery to build a plant around. Send him thanks, not me.

---

## What's in the box

| Layer | Component | Role |
| --- | --- | --- |
| **Retrieval — code** | jCodeMunch | Tree-sitter symbol index; structural slicing of source code |
| | Serena | LSP-backed code intelligence (Python/TS/Rust/Go/C#) |
| **Retrieval — data** | jDataMunch | CSV/TSV index + profiles/aggregations |
| | DuckDB MCP | SQL over Parquet/JSON/CSV/S3/GCS/R2 |
| **Retrieval — docs** | jDocMunch | Your project docs, section-precise |
| | Context7 | Third-party library docs, version-pinned |
| **Retrieval — memory** | MemPalace | Long-term verbatim memory with semantic search |
| **Efficiency — output** | jOutputMunch | System-prompt rules that cut output tokens 25-40% |
| **Reliability** | Superpowers | 20+ skills: brainstorming, TDD, systematic debugging, verification |
| | Ralph Wiggum | Autonomous loop harness with verification gates |
| | prior-art-check | Custom skill — forces MemPalace lookup before non-trivial work |
| | judge | Custom skill — spawns code-reviewer subagent before Edit/Write |
| **Governance** | jCodeMunch hooks | PreToolUse / PostToolUse / PreCompact / TaskCompleted / SubagentStart enforcement |
| | dwarvesf guardrails | UserPromptSubmit secret scanner + PostToolUse prompt-injection defender |
| | Bash-matcher rules | Block destructive `rm`, pipe-to-shell, direct pushes to main, exfil to webhook services, escalation flags |
| **Observability** | Langfuse | Self-hosted (Docker) — every assistant turn traced with tool calls, timings, token counts |
| **Optional features** | Telegram gateway | Bidirectional Claude ↔ Telegram; message Claude from your phone, get replies within 2 min |
| | Telegram notify | Stop hook — sends a Telegram notification when each Claude session ends |
| | Dreaming | Daily Langfuse trace mining → mistake patterns + playbooks → MemPalace + CLAUDE.md |
| | Session stats | Weekly Langfuse efficiency reporter; flags high-token sessions; feeds dreaming |
| | Auto-skill | Stop hook — suggests relevant skills based on session tool use |
| | Skill manager | Symlinks `global-skills/` + per-project `skills/` into `~/.claude/skills/` at session start |
| | Ralph cron | Installs per-PRD cron jobs that run the verification-gated Ralph harness on a schedule |
| | MemPalace automation | Stop hook (convo mining) + daily cron (project mining) — keeps palace current automatically |

All 7 MCP servers register at **user scope**, so they're live in every
Claude Code project on this machine automatically.

---

## Commercial use — read before you ship

Most of this stack is MIT and safe for commercial use. Three pieces are
**not** straight MIT and need your attention if you're deploying this
anywhere that makes money — a company, paid client work, or
revenue-generating product. **This section is near the top deliberately:
do not treat it as fine print.**

**1. Uncle J's tools (jCodeMunch, jDataMunch, jDocMunch, jOutputMunch)**

Free for personal use. If you use them to make money, Uncle J. gets a
taste. Fair enough?

- [Free for personal use](https://github.com/jgravelle/jcodemunch-mcp#free-for-personal-use)
- [Commercial licenses](https://github.com/jgravelle/jcodemunch-mcp#commercial-licenses)

Square up with Uncle J. directly via the commercial-licenses link
before shipping a commercial deployment.

**2. Claude Code + Ralph Wiggum plugin (Anthropic)**

Claude Code itself isn't open-source. Its `LICENSE.md` reads:
"© Anthropic PBC. All rights reserved. Use is subject to Anthropic's
Commercial Terms of Service." The Ralph Wiggum plugin ships from the
same `anthropics/claude-code` repo and inherits those terms.

Commercial use is governed by [Anthropic's Commercial Terms of Service](https://www.anthropic.com/legal/commercial-terms).
Redistribution and modification are not granted by default.

**3. Langfuse (self-hosted)**

Everything outside the `/ee` folders is MIT — free for commercial use
with no usage limits. The `/ee` folder contains enterprise-only
features (SCIM, audit logs, data retention policies) that require a
commercial license if you want to enable them in a self-hosted
deployment. See [Langfuse open-source FAQ](https://langfuse.com/docs/open-source).

**Everything else** — MemPalace, Serena, DuckDB MCP, Context7,
Superpowers, dwarvesf/claude-guardrails, and the Langfuse template —
is MIT-licensed. No commercial restrictions. Attribution per the MIT
terms is the only requirement. (Serena's core MCP is MIT; their
separate JetBrains IDE plugin is a paid product, not used by this
stack.)

---

## Prerequisites

- Bash 4+
- Python 3.11+ (auto-installed via `uv` if missing)
- Node.js 18+ (for Context7)
- Git 2.30+
- Docker + Docker Compose plugin (for Langfuse — optional but recommended)
- ~15 GB free disk (Langfuse images are ~5 GB; Postgres/ClickHouse/MinIO grow as they run)
- Internet connection (first run pulls ~2 GB of Python/Node/Docker packages)

The installers detect missing prerequisites and either auto-install them
(where safe — e.g., `uv`) or tell you what to `apt`/`dnf`/`brew`
and bail cleanly.

---

## Quick install

```bash
./prerequisites.sh          # git, node, claude via your distro's package manager
./install.sh --auto-register
./verify.sh                 # expect all PASS
cp CLAUDE.md.merged ~/.claude/CLAUDE.md
./install-reliability.sh
./install-guardrails.sh
./install-langfuse.sh
```

Details on each step are below.

---

## Install — step by step

All commands run from the repo root (`_stack_setup/` or wherever you
cloned this).

### 1. OS-level prerequisites

Installs git, Node.js LTS, and the Claude Code CLI via your OS package
manager. Idempotent — skips anything already present.

```bash
./prerequisites.sh
```

On **Debian/Ubuntu** it uses `apt-get`. On **Fedora/RHEL** it uses `dnf`.
On **Arch** it uses `pacman`. On **macOS** it uses `brew`.

### 2. Python stack + MCP server registration

```bash
./install.sh --auto-register
```

1. Installs `uv` (fast Python package manager) if missing.
2. Creates `.venv/` via `uv venv --python 3.11`.
3. `uv sync` — installs jcodemunch-mcp, jdatamunch-mcp, jdocmunch-mcp, mempalace.
4. Warm-caches Serena and DuckDB MCP via uvx.
5. Runs `jcodemunch-mcp init --yes --hooks --audit` — installs enforcement
   hooks into `~/.claude/settings.json` and appends the routing policy to
   `~/.claude/CLAUDE.md`.
6. With `--auto-register`: runs `claude mcp add -s user ...` for all 7
   servers.

### 3. Verify

```bash
./verify.sh
```

Expect **all PASS**. See [§ Troubleshooting](#troubleshooting) if anything
fails — the usual culprit is a missing prereq that prerequisites.sh
couldn't cover (rare).

### 4. Confirm MCP servers

```bash
claude mcp list
```

All seven should show `✓ Connected`. The three Google remotes
(Drive/Gmail/Calendar) show `! Needs authentication` until you OAuth
them via `/mcp` inside Claude Code — normal.

### 5. Install the global routing policy

```bash
cp CLAUDE.md.merged ~/.claude/CLAUDE.md
```

This file combines:
- The retrieval-stack routing policy (which tool to use when)
- Security rules
- **jOutputMunch** — output-efficiency rules that force concise responses

### 6. Reliability layer

```bash
./install-reliability.sh
```

Installs:
- `~/.claude/skills/prior-art-check/SKILL.md` — forces MemPalace lookup on non-trivial prompts
- `~/.claude/skills/judge/SKILL.md` — spawns code-reviewer subagent with structural evidence before Edit/Write
- Clones `dwarvesf/claude-guardrails` into `claude-guardrails/` (real install in step 7)

Then, inside a `claude` session, install the two Anthropic plugins:

```
/plugin marketplace add anthropics/claude-code
/plugin install superpowers@claude-plugins-official
/plugin install ralph-wiggum@anthropics-claude-code
/reload-plugins
```

Superpowers adds 20+ battle-tested skills (brainstorming, systematic
debugging, TDD enforcement, requesting-code-review, verification-before-
completion). Ralph adds `/ralph-loop` for autonomous agent loops.

### 7. Guardrails

```bash
./install-guardrails.sh
```

Installs `jq` if missing, then delegates to dwarvesf's upstream
`install.sh`. That script does a proper jq-based deep-merge of
`~/.claude/settings.json` so the jCodeMunch hooks already in place stay
intact.

Result: two new hooks:
- `UserPromptSubmit` → `scan-secrets.sh` — blocks pasted credentials
- `PostToolUse` (Read/WebFetch/Bash/mcp__.*) → `prompt-injection-defender.sh`

Plus five `PreToolUse` Bash-matcher entries that block destructive `rm`,
pipe-to-shell, direct pushes to main, exfil to webhook.site/ngrok, and
escalation flags.

### 8. Langfuse (observability)

```bash
./install-langfuse.sh
```

First run checks for Docker. On Linux, if Docker isn't installed:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
# Log out and back in (or run `newgrp docker`) so group membership takes effect
```

Then:

1. Clones `doneyli/claude-code-langfuse-template` into `claude-code-langfuse-template/`
2. Pins ClickHouse to `24.8` and injects a `/sys/fs/cgroup/cpu.max`
   bind-mount for the container (works around a `std::stof("")` crash seen
   when the host's cgroup-v2 `cpu.max` is 0-byte — Linux 6.18 Liquorix
   reproduces it reliably; harmless on other hosts)
3. Generates `.env` with random secure credentials via `scripts/generate-env.sh`
4. Runs `docker compose up -d` with a 3-attempt retry loop (pulls ~5 GB
   of images; first boot takes 90-120s)
5. Copies `hooks/langfuse_hook.py` into `~/.claude/hooks/` directly —
   bypasses upstream `scripts/install-hook.sh` whose naked
   `pip install langfuse` trips PEP 668 on Debian 13
6. Installs `langfuse>=3.0,<4` into the stack venv (not system Python)
7. Patches `~/.claude/settings.json` with a Stop hook pointing at the
   venv interpreter plus the `LANGFUSE_*` / `TRACE_TO_LANGFUSE` env block

**Langfuse UI:** http://localhost:3050. Login with `admin@localhost.local`
and the password in `claude-code-langfuse-template/.env`
(`LANGFUSE_INIT_USER_PASSWORD`).

### 9. MCP performance tuning (optional)

`install.sh` already writes `MCP_TIMEOUT=60000` into
`~/.claude/settings.json`'s `env` block, so Claude Code has a 60s budget
for MCP server cold-starts out of the box (default is 30s, which Serena
and MotherDuck can blow past on first `uvx` fetch).

Three MCP servers default to `uvx` / `npx` invocations that re-resolve
packages on every launch. If you want faster cold-starts (14–24s → 7–18s)
you can install them as real binaries and re-register:

**Linux/macOS:**
```bash
uv tool install --from git+https://github.com/oraios/serena serena-agent
uv tool install mcp-server-motherduck

# If npm's default global prefix requires root (i.e. `npm prefix -g` returns /usr/local),
# configure a user-local one first so no sudo is needed:
[ "$(npm prefix -g)" = "/usr/local" ] && npm config set prefix ~/.npm-global
npm install -g @upstash/context7-mcp

claude mcp remove serena
claude mcp add -s user serena -- "$HOME/.local/bin/serena" start-mcp-server --context ide-assistant

claude mcp remove duckdb
claude mcp add -s user duckdb -- "$HOME/.local/bin/mcp-server-motherduck" --db-path :memory: --read-write --allow-switch-databases

claude mcp remove context7
claude mcp add -s user context7 -- "$(npm prefix -g)/bin/context7-mcp"

claude mcp list
```

### 10. (Optional) Stack update alerts

`install.sh` offers this as a yes/no prompt at the end. To enable it separately:

```bash
bash features/stack-alerts/install.sh
```

Requires a Telegram bot token and your chat ID (see `features/stack-alerts/README.md`).
Once installed, a daily cron job checks for new releases, invokes Claude to assess relevance,
and sends you an inline-button Telegram pitch. Tap ✅ and Claude upgrades the package; tap ❌ and it's silently dropped.

**Git is the golden reference.** The four core Python packages (`jcodemunch-mcp`, `jdatamunch-mcp`, `jdocmunch-mcp`, `mempalace`) are installed from their GitHub repos via `uv`, not from PyPI. The lockfile (`uv.lock`) pins exact commit SHAs. The freshness check compares the locked SHA against `HEAD` on each repo — a PyPI release is not required for an update to be available.

To run the freshness check manually at any time:

```bash
bash scripts/check-stack-freshness.sh
```

The check covers three tiers:

| Tier | Tools | Action threshold |
|---|---|---|
| **git packages** | jcodemunch, jdatamunch, jdocmunch, mempalace | Behind HEAD → upgrade |
| **Langfuse** | langfuse, langfuse-worker | New version available → pull |
| **Langfuse infrastructure** | ClickHouse, Redis, Postgres | New major exists but shown as informational — only update if Langfuse release notes require it |

MinIO uses a Chainguard image that auto-patches CVEs without changing behavior — no action needed.

To upgrade Python packages to latest HEAD:

```bash
cd "$STACK_ROOT"   # wherever you cloned the repo
uv lock --upgrade-package jcodemunch-mcp --upgrade-package jdatamunch-mcp \
  --upgrade-package jdocmunch-mcp --upgrade-package mempalace && uv sync --inexact
```

### Post-merge hook — automatic pull alerts

`install.sh` wires a `git post-merge` hook that fires every time you `git pull` on this repo. It detects new features, changed `install.sh`, updated `CLAUDE.md`, and new skills, then sends a Telegram alert (or prints to terminal if Telegram isn't configured) listing what needs action. New users get this automatically after running `install.sh`.

### 11. (Optional) GitHub Webhook Server

Receives GitHub events and acts on them automatically — no polling, instant response.

| Event | Action |
|---|---|
| `push` | Runs `verify.sh`, sends health check result to Telegram |
| `pull_request` opened/updated | Fetches the diff, Claude auto-reviews, posts GitHub comment |

**Requires** a public URL pointing at this machine — [ngrok](https://ngrok.com), [Tailscale Funnel](https://tailscale.com/kb/1223/funnel), or a VPS. The machine must be always on.

```bash
bash features/github-webhook/install.sh
```

The installer checks dependencies, prompts for your public URL, generates a webhook secret, installs a systemd user service, and registers the webhook on GitHub automatically.

Full setup guide: [`features/github-webhook/README.md`](features/github-webhook/README.md)

### 12. (Optional) Bootstrap MemPalace

MemPalace is installed but empty. To get value:

```bash
./.venv/bin/mempalace init ~/path/to/a/project
./.venv/bin/mempalace mine ~/path/to/a/project
./.venv/bin/mempalace mine ~/.claude/projects/ --mode convos
```

The last line ingests all your Claude Code sessions so `mempalace search
"why did we switch to X"` returns hits from day one.

### 13. (Recommended) MemPalace remote backup — keep memories across machines

Your MemPalace palace lives at `~/.mempalace/palace` — outside the repo,
outside any container. If you wipe the machine or switch computers, it's gone
unless you have a remote copy.

**What's stored there:** everything Claude has learned across all sessions —
decisions, patterns, prior art, playbooks. It grows to several GB over months.
Worth protecting.

#### One-time setup

1. Install rclone (once per machine):

```bash
# Linux
sudo apt install rclone   # or: curl https://rclone.org/install.sh | sudo bash

# macOS
brew install rclone
```

2. Configure a remote backend (S3, GCS, Dropbox, Backblaze B2, SFTP, etc.):

```bash
rclone config   # follow the interactive prompts — creates ~/.config/rclone/rclone.conf
```

3. Set `MEMPALACE_REMOTE` in your Claude Code env so the backup cron picks it up:

```bash
# Add to ~/.claude/settings.json under "env":
#   "MEMPALACE_REMOTE": "myremote:my-bucket/mempalace"
#
# Or for a one-liner:
python3 - <<'PY'
import json, pathlib
p = pathlib.Path.home() / ".claude/settings.json"
d = json.loads(p.read_text()) if p.exists() else {}
d.setdefault("env", {})["MEMPALACE_REMOTE"] = "myremote:my-bucket/mempalace"
p.write_text(json.dumps(d, indent=2))
print("written")
PY
```

Replace `myremote:my-bucket/mempalace` with your actual rclone remote and path.

After this, the existing 6-hour backup cron (`mempalace-backup.sh`) will sync
the live palace to your remote automatically after each local snapshot.

#### Restoring on a new machine

After running the full installer (`./install.sh`), pull your palace down before
starting Claude Code:

```bash
rclone copy myremote:my-bucket/mempalace ~/.mempalace/palace
```

That's it. The palace is immediately usable — no re-mining needed.

#### Working across two machines simultaneously

ChromaDB does not support concurrent writers. **Do not point two active Claude
Code instances at the same remote palace simultaneously** — you will corrupt it.

Safe pattern: one machine is active at a time. When switching:

1. On machine A: wait for the next backup cron to fire (or run
   `bash mempalace-backup.sh` manually) so the remote is current.
2. On machine B: `rclone copy myremote:my-bucket/mempalace ~/.mempalace/palace`
   before starting Claude Code.

#### Merging two diverged palaces

If two machines both accumulated sessions independently (no shared remote),
merging is not automatic. Best recovery path:

```bash
# On the receiving machine, re-mine both sets of session traces:
./.venv/bin/mempalace mine ~/.claude/projects/ --mode convos
# Then copy the other machine's session traces over (~/.claude/projects/) and mine again.
```

Manually-written drawers (not derived from sessions) must be migrated by hand
via `mempalace export` / `mempalace import` if those commands are available in
your version, or by copying drawer files directly from the palace SQLite.

### 14. (Optional) Telegram gateway — send messages to Claude from Telegram

The gateway polls your Telegram bot every 2 minutes and forwards messages to
Claude via `claude -p`. Claude's response is sent back to the chat. Requires
stack-alerts (step 10) to be installed first — the gateway reuses the same bot
token and chat ID.

```bash
bash features/telegram-gateway/install.sh
# uninstall: bash features/telegram-gateway/install.sh --uninstall
```

Security: the gateway enforces rate limits, input sanitization (injection
patterns, dangerous Unicode, over-length inputs), output scanning (path/secret
redaction), and an anti-disclosure system prompt so the bot never leaks OS,
kernel, or infra details over the channel. All implemented in
`scripts/lib/tg_security.py`.

Logs: `state/telegram-gateway.log`

### 15. (Optional) Telegram notify — session-end notifications

A Stop hook that sends you a Telegram message when each Claude Code session
ends, including a one-line summary of what Claude did. Requires
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` (set by step 10).

```bash
bash features/telegram-notify/install.sh
# uninstall: bash features/telegram-notify/install.sh --uninstall
```

### 16. (Optional) Dreaming — automatic playbook extraction

Queries Langfuse for traces from the past day, synthesizes recurring mistakes
and proven playbooks via the `dream-synthesizer` skill, writes dated output to
`~/.claude/dreaming-output/`, ingests into MemPalace (wing: `dreaming`), and
appends proven playbooks to `~/.claude/CLAUDE.md` idempotently.

```bash
bash features/dreaming/install.sh
# manual trigger any time:
bash features/dreaming/dream.sh
# or from inside Claude Code: /dream
```

Runs daily at 2 AM by default (`DREAMING_CRON_SCHEDULE` in
`state/dreaming.env`). See `features/dreaming/README.md` for full config.

### 17. (Optional) Session stats — weekly efficiency reporter

Queries Langfuse for the past 7 days of sessions, renders a markdown table
(date, project, traces, tool calls, tokens), flags sessions exceeding 40k
tokens, and writes output that Dreaming picks up on its next run.

```bash
bash features/session-stats/install.sh
# manual trigger: bash features/session-stats/stats.sh
# or from inside Claude Code: /stats
```

Runs every Sunday at 8 AM by default. See `features/session-stats/README.md`.

### 18. (Optional) Auto-skill — skill suggestions after each session

A Stop hook that inspects what tools were called during a session and suggests
relevant skills you haven't used recently. Drafts go to `state/skill-drafts/`.

```bash
bash features/auto-skill/install.sh
# uninstall: bash features/auto-skill/install.sh --uninstall
```

### 19. (Optional) Skill manager — global + per-project skill symlinks

Symlinks every skill in `global-skills/` into `~/.claude/skills/` once at
install time, and installs SessionStart / Stop hooks that symlink/remove the
per-project `skills/` directory so project-specific skills are available only
while you're in that project.

```bash
bash features/skill-manager/install.sh
# uninstall: bash features/skill-manager/install.sh --uninstall
```

### 20. (Optional) Ralph cron — scheduled autonomous Ralph runs

Installs a cron job that runs the verification-gated Ralph harness against a
given PRD file on a schedule you choose interactively.

```bash
bash features/ralph-cron/install.sh
bash features/ralph-cron/install.sh --list       # show installed ralph crons
bash features/ralph-cron/install.sh --uninstall MARKER
```

### 21. (Optional) MemPalace automation — keep the palace current automatically

Installs a Stop hook that mines `~/.claude/projects/` after every session
(conversation mode) and a daily 3 AM cron that mines the project repo (code
mode). Without this, you must run `mempalace mine` manually.

```bash
bash features/mempalace/install.sh
# uninstall: bash features/mempalace/install.sh --uninstall
```

---

## Daily usage

Just use Claude Code normally. The stack is global — every project, every
session, the routing policy and hooks apply automatically. Signs it's
working:

- Claude reaches for `search_symbols` / `get_file_outline` instead of
  `Read` on a source file
- Responses don't start with "Great question!" or end with "I hope this
  helps!"
- Traces appear in Langfuse within seconds of each turn
- Destructive commands get blocked before they run

### Per-project customization

Add a `CLAUDE.md` to any repo root to override or extend the global
policy for that project only. Add a `.claude/settings.local.json` for
per-project MCP servers, hooks, or permissions.

### Skipping permission prompts for a folder

```bash
mkdir -p .claude
cat > .claude/settings.local.json <<'EOF'
{
  "permissions": {
    "defaultMode": "acceptEdits",
    "allow": ["Bash(*)", "Edit(*)", "Write(*)"]
  }
}
EOF
```

Never do this globally or in a folder containing credentials.

### Using Ralph (autonomous loop)

```bash
./ralph-harness.sh --prd ./PRD.md --repo /path/to/repo
```

Our harness uses the retrieval stack's verification tools
(`get_pr_risk_profile < 0.65`, `get_untested_symbols == 0`, PRD marked
DONE) as exit criteria — solves Ralph's classic failure mode of
declaring victory on a broken change. Starting template at
`prd-template.md`.

### Runtime health check

`verify.sh` confirms binaries exist. `healthcheck.sh` confirms the stack
is actually wired up and responding. Use it to catch silent regressions
that install-time checks miss (MCP server registered at wrong scope,
`langfuse` wiped from the venv by a `uv sync`, Langfuse container died
overnight, etc.).

```bash
./healthcheck.sh            # --quick (default, ~6s)
./healthcheck.sh --full     # + nested claude -p smoke + Langfuse trace API (~60s)
```

The script is **read-only** — failures include the remediation command
in the `fix:` line; they do not auto-heal. Final stdout line is
machine-parseable: `HEALTHCHECK: ok` or
`HEALTHCHECK: fail (<n>) -- <first failing check>`.

Automated invocation:

- **SessionStart hook** — `healthcheck.sh --quick` runs at the start
  of every Claude Code session (configured in
  `~/.claude/settings.json`). Banner prints as a system-reminder at
  session open; no-ops silently when you open a session outside this
  repo.
- **`/health` slash command** — runs `healthcheck.sh --full` on
  demand mid-session. Lives at `~/.claude/commands/health.md`.

---

## Troubleshooting

### `HEALTHCHECK: fail` in the SessionStart banner

The banner's `fix:` line tells you what to run. The most common causes,
mapped to their fixes:

| Banner says | Fix |
|---|---|
| `mcp-servers-down(jcodemunch)` etc | `./install.sh --auto-register` |
| `jcodemunch-wrong-scope` | `claude mcp remove jcodemunch -s local ; claude mcp remove jcodemunch -s project` |
| `mcp-timeout` | Re-run `./install.sh` — step 5b rewrites `MCP_TIMEOUT=60000` |
| `docker-down` / `langfuse-unhealthy` | `docker compose -f claude-code-langfuse-template/docker-compose.yml up -d` |
| `langfuse-sdk-missing` | Re-run `./install-langfuse.sh` |
| `mempalace-sqlite` | `sqlite3 ~/.mempalace/palace/chroma.sqlite3 "INSERT INTO embedding_fulltext_search(embedding_fulltext_search) VALUES('rebuild');"` |
| `mempalace-stale-lock` | `rmdir state/mempalace-mine-convos.lock state/mempalace-mine-project.lock 2>/dev/null` — or wait; locks now auto-clear after 30 min |
| `mempalace-hnsw-corruption` | Run `/mempalace-hnsw-corruption-fix` skill |
| `cron-missing(...)` | Re-run `./install.sh` — crons are registered in step 6d |
| `stack-not-at-head` | `cd "$STACK_ROOT" && uv lock --upgrade-package jcodemunch-mcp --upgrade-package jdatamunch-mcp --upgrade-package jdocmunch-mcp --upgrade-package mempalace && uv sync --inexact` |
| `post-merge-hook-missing` | `ln -sfn "$STACK_ROOT/scripts/post-merge-hook.sh" "$STACK_ROOT/.git/hooks/post-merge"` |
| `secrets` | Review the grep hits; add to `.gitignore` or redact |
| `hook-no-fire` / `trace-api` (full mode only) | Check `tail -5 ~/.claude/state/langfuse_hook.log`, then verify `from langfuse import Langfuse` works from the stack venv |


### `verify.sh` reports FAIL after fresh install

Check `echo $PATH` and make sure `~/.local/bin` is on it (where `uv`
and the installed MCP binaries live). Add to your shell RC if not:
`export PATH="$HOME/.local/bin:$PATH"`.

### MCP servers show ✗ Failed to connect

Either they hit the startup timeout or they're actually broken. Check
the timeout inside Claude's config, not the shell env — that's where
`install.sh` writes it:

```bash
python3 -c "import json; d=json.loads(open(f\"{__import__('os').path.expanduser('~')}/.claude/settings.json\").read()); print(d.get('env',{}).get('MCP_TIMEOUT','<unset>'))"
# expect: 60000
```

If it's `<unset>` or below 60000, re-run `install.sh --auto-register`.
If it's set and servers still fail, follow step 9 to install them as
real binaries and re-register.

### jcodemunch registered as `uvx jcodemunch-mcp` instead of the venv path

`jcodemunch-mcp init` self-registers as `uvx jcodemunch-mcp` in Claude
Code during step 2. `install.sh` removes + re-adds with the venv path
so re-runs always converge. If you see this on an older install:

```bash
claude mcp remove jcodemunch
claude mcp add -s user jcodemunch "$STACK_ROOT/.venv/bin/jcodemunch-mcp"
# or just re-run:
./install.sh --auto-register
```

### Langfuse ClickHouse crashes with `std::stof: no conversion`

Seen on Linux 6.18 Liquorix; may affect other kernels where the
container's `/sys/fs/cgroup/cpu.max` is a 0-byte file. ClickHouse's
startup tries to parse it with `std::stof` and dies during global-static
init. `install-langfuse.sh` injects a bind-mount of a `max 100000` file
over that path. If you see the crash on a host where the installer
didn't apply the workaround (older tag, custom docker-compose), add:

```yaml
# under the clickhouse service's volumes:
- ./clickhouse/cpu.max.override:/sys/fs/cgroup/cpu.max:ro
```

with `./clickhouse/cpu.max.override` containing the line `max 100000`.

### Langfuse UI is up but traces don't appear

Check the hook log:

```bash
tail -30 ~/.claude/state/langfuse_hook.log
```

Common failures:
- `'Langfuse' object has no attribute 'start_as_current_span'` → langfuse
  SDK is v4+. Downgrade: `python3 -m pip install "langfuse>=3.0,<4"`
- `Langfuse API keys not set` → env block missing the keys. Re-run
  `./install-langfuse.sh` — it re-patches.
- Empty log, hook dir missing → `mkdir -p ~/.claude/state`

### Langfuse containers fail to start (`dependency failed to start`)

MinIO, Postgres, or ClickHouse failed health check. Usually disk pressure.

```bash
df -h /
docker system df
```

If less than 10 GB free: free space, or point Docker's data-root at a
different mount (`/etc/docker/daemon.json`, key `data-root`). Then:

```bash
cd claude-code-langfuse-template
docker compose down -v
docker compose up -d
```

The `-v` drops half-initialized volumes so they recreate cleanly.

### Claude Code keeps asking for permissions

Per-folder: see "Skipping permission prompts" above.

Per-session (fast escape hatch): `claude --dangerously-skip-permissions`.

Inside a running session: `/permissions` opens the interactive editor.

### jOutputMunch rules aren't taking effect

Verify they're in the global CLAUDE.md:

```bash
grep -c jOutputMunch ~/.claude/CLAUDE.md
```

Expect `1` or more. If `0`, re-run step 5 (`cp CLAUDE.md.merged ~/.claude/CLAUDE.md`).

### Something is broken, reset and try again

```bash
# Back up first
cp -r ~/.claude ~/.claude.bak.$(date +%Y%m%d-%H%M%S)

# Stop Langfuse
(cd claude-code-langfuse-template && docker compose down -v)

# Remove MCP registrations
for s in jcodemunch jdatamunch jdocmunch mempalace serena duckdb context7; do
    claude mcp remove "$s" 2>/dev/null
done

# Remove venv
rm -rf .venv .venv-test
```

Re-run from step 2.

---

## File map

```
_stack_setup/
├── README.md                           ← this file
├── CLAUDE.md                           ← base routing policy
├── CLAUDE.md.merged                    ← full policy: routing + security + jOutputMunch (cp to ~/.claude/)
├── AGENTS.md                           ← agent-facing policy mirror
├── CHANGELOG.md                        ← version history
├── HANDOFF.md                          ← overnight-handoff brief + work log
├── PORTING.md                          ← notes for porting to a new machine
├── PRD.md                              ← Ralph-driven maintenance PRD
├── prd-template.md                     ← starting template for Ralph tasks
├── pyproject.toml                      ← uv-managed Python deps
├── uv.lock
├── mempalace.yaml                      ← MemPalace wing/room configuration
├── mempalace-backup.sh                 ← rclone sync of ~/.mempalace/palace to remote
├── mempalace-health.py                 ← SQLite health probe used by healthcheck.sh
├── patch-jcodemunch-hook-paths.py      ← one-time fix for hook path mismatches after move
├── LICENSE                             ← MIT for the glue; upstream licenses apply to each dep
├── .venv/                              ← real Python venv created by install.sh (gitignored)
│
├── prerequisites.sh                    ← step 1: git/node/claude
├── install.sh                          ← step 2: Python stack + MCP registration
├── finish-install.sh                   ← re-attempt after shell refresh
├── verify.sh                           ← step 3: all-pass sanity check
├── healthcheck.sh                      ← runtime health check (--quick / --full)
├── install-reliability.sh              ← step 6: custom skills + guardrails clone
├── install-guardrails.sh               ← step 7: dwarvesf guardrails via upstream install.sh
├── install-langfuse.sh                 ← step 8: Docker + Langfuse + Stop hook
├── ralph-harness.sh                    ← verification-gated Ralph loop
│
├── scripts/
│   ├── auto-maintain.sh                ← scheduled self-maintenance runner
│   ├── check-stack-freshness.sh        ← checks installed vs latest for all MCP tools
│   ├── github-webhook-server.py        ← HTTP server for GitHub push/PR events
│   ├── jcodemunch-reindex.sh           ← triggers jcodemunch re-index after significant changes
│   ├── mempalace-mcp-start.sh          ← wrapper that starts the mempalace MCP server
│   ├── mempalace-mine-convos.sh        ← mines ~/.claude/projects/ (conversation mode)
│   ├── mempalace-mine-project.sh       ← mines the project repo (code mode)
│   ├── post-merge-hook.sh              ← git post-merge hook; alerts on new features
│   ├── ralph-cron-run.sh               ← runs ralph-harness.sh for a given PRD (cron target)
│   ├── review-check.sh                 ← runs the code review checklist
│   ├── session-notify.sh               ← sends Telegram notification on session end
│   ├── skill-link.sh                   ← symlinks a skill into ~/.claude/skills/
│   ├── skill-suggest.sh                ← analyzes session tool use and suggests skills
│   ├── stack-alerts-poll.sh            ← polls Telegram for replies to upgrade pitches
│   ├── stack-alerts-send.sh            ← sends upgrade pitch to Telegram
│   ├── telegram-gateway-poll.sh        ← polls Telegram for user messages; routes to claude -p
│   └── lib/
│       ├── __init__.py
│       └── tg_security.py              ← input sanitizer, output scanner, path validator, rate limiter
│
├── lib/
│   ├── feature-helpers.sh              ← shared installer utilities (prompt, write_env_var, cron)
│   ├── notify.sh                       ← notification dispatcher (reads NOTIFY_CHANNEL)
│   └── notify-telegram.sh              ← Telegram backend (send pitch, poll reply, send text)
│
├── features/
│   ├── auto-skill/
│   │   └── install.sh                  ← Stop hook: suggests skills based on session tool use
│   ├── dreaming/
│   │   ├── install.sh                  ← daily Langfuse trace mining → MemPalace + CLAUDE.md
│   │   ├── dream.sh                    ← manual trigger
│   │   ├── dream.md                    ← /dream slash command
│   │   ├── README.md                   ← full feature docs
│   │   └── skills/                     ← dream-synthesizer skill (installed to ~/.claude/skills/)
│   ├── github-webhook/
│   │   ├── install.sh                  ← systemd user service + GitHub webhook registration
│   │   └── README.md                   ← setup guide, public URL requirements
│   ├── mempalace/
│   │   └── install.sh                  ← Stop hook (convos) + daily cron (project) mining
│   ├── ralph-cron/
│   │   └── install.sh                  ← per-PRD cron jobs for scheduled Ralph runs
│   ├── session-stats/
│   │   ├── install.sh                  ← weekly Langfuse reporter + /stats command
│   │   ├── stats.sh                    ← manual trigger
│   │   ├── stats.md                    ← /stats slash command
│   │   └── README.md                   ← full feature docs
│   ├── skill-manager/
│   │   └── install.sh                  ← symlinks global-skills/ + project skills/ at session start
│   ├── stack-alerts/
│   │   ├── install.sh                  ← interactive setup: Telegram creds + cron
│   │   └── README.md                   ← feature docs, prerequisites, uninstall
│   ├── telegram-gateway/
│   │   └── install.sh                  ← cron poll: Telegram → claude -p → Telegram reply
│   └── telegram-notify/
│       └── install.sh                  ← Stop hook: Telegram notification on session end
│
├── global-skills/                      ← project-agnostic skills, symlinked to ~/.claude/skills/
│   ├── deep-repo-analysis/
│   ├── fog-of-chess-engine-mode-implementation/
│   ├── freecad-parametric-toolkit-build/
│   ├── judge/
│   ├── mcp-index-empty-diagnosis/
│   ├── mempalace-hnsw-corruption-fix/
│   ├── milestone-tier-implementation/
│   ├── orchestrator/
│   ├── outcomes/
│   ├── per-task-review-cycle/
│   ├── post-upgrade-mcp-integration/
│   ├── prior-art-check/
│   ├── stack-not-at-head-remediation/
│   ├── stale-lock-diagnosis/
│   ├── stale-pending-memory-guard/
│   ├── telegram-gateway-security-audit/
│   ├── validate-external-audit/
│   └── verify-handoff-claims/
│
├── skills/                             ← per-project skills (symlinked only in this repo's sessions)
│
├── tests/
│   ├── __init__.py
│   └── test_tg_security.py             ← pytest suite for scripts/lib/tg_security.py
│
├── state/                              ← runtime state (gitignored except .gitkeep)
│   ├── stack-alerts-pending.json       ← written by send job, deleted by poll job on reply
│   ├── telegram-gateway-offset.txt     ← Telegram update_id watermark (dedup)
│   ├── telegram-gateway.log
│   ├── telegram-gateway-ratelimit.json
│   ├── dreaming.env                    ← dreaming feature config (gitignored)
│   ├── dreaming.log
│   ├── session-stats.env               ← session-stats config (gitignored)
│   └── skill-drafts/                   ← auto-skill draft suggestions
│
├── docs/
│   ├── STACK.md                        ← one-page-per-tool reference
│   └── RELIABILITY.md                  ← reliability-layer deep dive
│
├── mcp-clients/
│   ├── claude-code-mcp.json.tmpl       ← templates rendered at install time
│   ├── claude-desktop-config-fragment.json.tmpl
│   ├── cursor-mcp.json.tmpl
│   ├── windsurf-mcp.json.tmpl
│   └── *.json                          ← rendered outputs (gitignored)
│
├── claude-guardrails/                  ← cloned dwarvesf/claude-guardrails (gitignored)
└── claude-code-langfuse-template/      ← cloned doneyli/claude-code-langfuse-template (gitignored)
```

Sibling folders (outside `_stack_setup/`, under `Downloads/claude/`):

```
claude/
├── jcodemunch-mcp-main/                ← source archive
├── jdatamunch-mcp-master/              ← source archive
├── jdocmunch-mcp-master/               ← source archive
├── mempalace-develop/                  ← source archive
└── jOutputMunch-master/                ← rules + guides; integrated into ~/.claude/CLAUDE.md
```

---

## What lives where after install

```
~/.claude/
├── CLAUDE.md                           ← routing + security + jOutputMunch (from step 5)
├── settings.json                       ← hooks, env vars, permissions.deny
├── .claude.json                        ← MCP server registrations (managed by `claude mcp add`)
├── skills/
│   ├── prior-art-check/                ← from step 6 (or skill-manager)
│   ├── judge/                          ← from step 6 (or skill-manager)
│   ├── dream-synthesizer/              ← from features/dreaming
│   └── <others>/                       ← symlinked from global-skills/ by skill-manager
├── commands/
│   ├── dream.md                        ← /dream slash command (features/dreaming)
│   ├── stats.md                        ← /stats slash command (features/session-stats)
│   ├── health.md                       ← /health slash command
│   └── ...
├── hooks/
│   ├── langfuse_hook.py                ← Stop hook, step 8
│   ├── scan-secrets/                   ← guardrail, step 7
│   ├── scan-commit/                    ← guardrail, step 7
│   └── prompt-injection-defender/      ← guardrail, step 7
├── dreaming-output/                    ← dated dream + stats reports (feeds MemPalace)
│   ├── dream-YYYY-MM-DD.md
│   └── stats-YYYY-MM-DD.md
├── state/
│   ├── langfuse_hook.log
│   ├── langfuse_state.json
│   └── pending_traces.jsonl
├── projects/                           ← Claude Code session transcripts
└── logs/
    └── permission-events.jsonl
```

---

## Provenance

| Tool | Origin |
| --- | --- |
| jCodeMunch / jDataMunch / jDocMunch / jOutputMunch | [@jgravelle](https://github.com/jgravelle) |
| MemPalace | [mempalaceofficial.com](https://mempalaceofficial.com) |
| Serena | [oraios/serena](https://github.com/oraios/serena) |
| DuckDB MCP | [motherduckdb/mcp-server-motherduck](https://github.com/motherduckdb/mcp-server-motherduck) |
| Context7 | [@upstash/context7-mcp](https://www.npmjs.com/package/@upstash/context7-mcp) |
| Superpowers | [obra/superpowers](https://github.com/obra/superpowers) |
| Ralph Wiggum | [Anthropic claude-code marketplace](https://github.com/anthropics/claude-code) |
| Claude Guardrails | [dwarvesf/claude-guardrails](https://github.com/dwarvesf/claude-guardrails) |
| Langfuse template | [doneyli/claude-code-langfuse-template](https://github.com/doneyli/claude-code-langfuse-template) |

---

## Uninstall

```bash
# Stop Langfuse and drop its data
(cd claude-code-langfuse-template && docker compose down -v)

# Remove MCP registrations
for s in jcodemunch jdatamunch jdocmunch mempalace serena duckdb context7; do
    claude mcp remove "$s" 2>/dev/null
done

# Remove uv tool installs and npm globals
uv tool uninstall serena-agent mcp-server-motherduck
npm uninstall -g @upstash/context7-mcp

# Back up user config, then wipe stack-specific bits
cp -r ~/.claude ~/.claude.bak.$(date +%Y%m%d-%H%M%S)
rm -rf ~/.claude/hooks ~/.claude/skills/prior-art-check ~/.claude/skills/judge
rm -f ~/.claude/CLAUDE.md

# settings.json needs surgical editing — delete the LANGFUSE/TRACE_TO/
# PYTHONUTF8 env keys, remove the Stop hook entry, clear the jCodeMunch
# and guardrails entries from `hooks` if you want a clean slate.

# Remove the stack folder
cd ..
rm -rf _stack_setup
```

---

## License & credits

The glue in this repo — install scripts, merged CLAUDE.md, custom skills,
Ralph harness, templates — is MIT (see `LICENSE`). Each upstream
component retains its own license.

### Commercial use

See the top-of-document [§ Commercial use — read before you ship](#commercial-use--read-before-you-ship)
section for the license audit. Short version: Uncle J's tools need a
commercial license if you're making money with them, Claude Code + the
Ralph plugin are governed by Anthropic's Commercial ToS (not open
source), Langfuse `/ee` features need a paid license, everything else
is MIT.

### Primary credit — the namesake

**J. Gravelle ([@jgravelle](https://github.com/jgravelle))** built the
four tools this project is named for — jCodeMunch, jDataMunch,
jDocMunch, and jOutputMunch. Every reduction number quoted in this
README ultimately traces back to his "index once, query cheaply"
philosophy and the MUNCH compact wire format. "Uncle J's" is him.
If this stack saves you tokens, the credit belongs to him first.

### Also credit where due

- MemPalace team ([mempalaceofficial.com](https://mempalaceofficial.com)) — local-first semantic memory with best-in-class LongMemEval recall
- Oraios ([oraios/serena](https://github.com/oraios/serena)) — LSP-grade code intelligence MCP
- MotherDuck team — DuckDB MCP server that runs SQL over anything
- Upstash — Context7 for version-pinned third-party docs
- Obra — Superpowers skills pack, now in Anthropic's official marketplace
- Anthropic — Claude Code, the Ralph Wiggum plugin, the marketplace itself
- Dwarves Foundation ([dwarvesf/claude-guardrails](https://github.com/dwarvesf/claude-guardrails)) — the guardrails pattern (secret scanner + prompt-injection defender)
- Langfuse team + doneyli ([doneyli/claude-code-langfuse-template](https://github.com/doneyli/claude-code-langfuse-template)) — self-hostable observability
- Geoffrey Huntley — the original Ralph Wiggum `while true` agent pattern

Everything else in this repo — install scripts, the verification-gated
Ralph harness, the prior-art-check and judge skills, this README — is
integration glue. The hard work was done upstream.

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
and sends you an inline-button Telegram pitch. Tap ✅ and
Claude upgrades the package; tap ❌ and it's silently dropped.

To run the freshness check manually at any time:

```bash
bash scripts/check-stack-freshness.sh
```

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
| `langfuse-sdk-missing` | `uv pip install --python .venv/bin/python --upgrade 'langfuse>=3.0,<4'` (or re-run `./install-langfuse.sh`) |
| `secrets` | Review the grep hits; add to `.gitignore` or redact |
| `hook-no-fire` / `trace-api` (full mode only) | Check `tail -5 ~/.claude/state/langfuse_hook.log`, then verify `from langfuse import Langfuse` works from the stack venv |


### `verify.sh` / `verify.ps1` reports FAIL after fresh install

**Linux/macOS:** check `echo $PATH` and make sure `~/.local/bin` is on
it (where `uv` and the installed MCP binaries live). Add to your shell
RC if not: `export PATH="$HOME/.local/bin:$PATH"`.

**Windows:** PowerShell PATH is stale. Open a fresh window. If that
doesn't fix it, reboot — winget sometimes needs a full login to
propagate PATH changes from MSI installers.

### MCP servers show ✗ Failed to connect

Either they hit the startup timeout or they're actually broken. Check
the timeout inside Claude's config, not the shell env — that's where
`install.{sh,ps1}` writes it:

```bash
python3 -c "import json; d=json.loads(open(f\"{__import__('os').path.expanduser('~')}/.claude/settings.json\").read()); print(d.get('env',{}).get('MCP_TIMEOUT','<unset>'))"
# expect: 60000
```

If it's `<unset>` or below 60000, re-run `install.sh --auto-register`
(or `install.ps1 -AutoRegister`). If it's set and servers still fail,
follow step 9 to install them as real binaries and re-register.

### jcodemunch registered as `uvx jcodemunch-mcp` instead of the venv path

`jcodemunch-mcp init` self-registers as `uvx jcodemunch-mcp` in Claude
Code during step 2. `install.{sh,ps1}` removes + re-adds with the venv
path so re-runs always converge. If you see this on an older install:

```bash
claude mcp remove jcodemunch
claude mcp add -s user jcodemunch /opt/proj/Uncle-J-s-Refinery/.venv/bin/jcodemunch-mcp
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
- `UnicodeDecodeError ... cp1252` (Windows only) → `PYTHONUTF8=1` missing from
  `settings.json` env block. `install-langfuse.sh` handles this; re-run it.
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

Per-session (fast escape hatch): `claude --dangerously-skip-permissions`
(Linux/macOS/Windows, identical flag).

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

## Windows-specific notes

Windows is fully supported but has some extra gotchas that don't affect
Linux/macOS. Recording them here so Windows users aren't surprised.

**PATH propagation.** winget modifies PATH via the registry, but the
current shell reads PATH only at start. After `prerequisites.ps1` you
must open a fresh PowerShell window — or in a pinch, reboot.

**Store Python vs system Python.** If you install Python via the
Microsoft Store, `python3.13.exe` lives under `%LOCALAPPDATA%\Microsoft\WindowsApps\`
as an app-execution-alias stub. Packages install to a user-scoped
site-packages directory that the stub knows about. Works fine, but means
you can't `pip install --system` and expect it to land anywhere useful.

**Windows Python default encoding is cp1252.** The Langfuse hook reads
session transcripts that contain UTF-8 emoji. Without `PYTHONUTF8=1`
the hook dies on the first non-cp1252 byte. `install-langfuse.ps1`
sets this in `settings.json`.

**`npx` MCP servers need the `.cmd` shim.** Claude Code on Windows can't
invoke `.cmd` files from a spawned subprocess, so `claude mcp add -s user
context7 -- npx -y @upstash/context7-mcp` works but trips `/doctor`.
Either wrap with `cmd /c` or install the tool as a real binary via
`npm install -g` and point the registration at the resulting `.cmd`
directly (step 9 handles this).

**MCP 30s startup timeout.** `uvx`/`npx` MCP entries re-resolve packages
on every launch. `setx MCP_TIMEOUT 60000` + pre-installing the binaries.
Step 9.

**`permissions.deny` blocks editing `settings.json`.** Claude Code can't
edit its own settings file because it's in the deny list. Edit from
PowerShell — that's by design, prevents a session from escalating its
own permissions.

**`jq` winget package rename.** `stedolan.jq` became `jqlang.jq`.
`install-guardrails.ps1` tries both, falls back to a direct download
from the jqlang GitHub releases into `~/.local/bin`.

**Ralph marketplace name.** Ralph Wiggum is in the
`anthropics-claude-code` marketplace (from `/plugin marketplace add
anthropics/claude-code`), **not** `claude-plugins-official`. The latter
only has Superpowers.

---

## File map

```
_stack_setup/
├── README.md                           ← this file
├── CLAUDE.md                           ← base routing policy
├── CLAUDE.md.merged                    ← full policy: routing + security + jOutputMunch (cp to ~/.claude/)
├── AGENTS.md                           ← agent-facing policy mirror
├── pyproject.toml                      ← uv-managed Python deps
├── uv.lock
├── .venv/                              ← real Python venv created by install.sh (gitignored)
│
├── prerequisites.sh         prerequisites.ps1      ← step 1: git/node/claude
├── install.sh               install.ps1            ← step 2: Python stack + MCP registration
├── finish-install.sh        finish-install.ps1     ← re-attempt after shell refresh
├── verify.sh                verify.ps1             ← step 3: all-pass sanity check
├── install-reliability.sh   install-reliability.ps1 ← step 6: custom skills + guardrails clone
├── install-guardrails.sh    install-guardrails.ps1  ← step 7: dwarvesf guardrails via upstream install.sh
├── install-langfuse.sh      install-langfuse.ps1    ← step 8: Docker + Langfuse + Stop hook
├── ralph-harness.sh         ralph-harness.ps1      ← verification-gated Ralph loop
├── prd-template.md                                 ← starting template for Ralph tasks
│
├── scripts/
│   ├── check-stack-freshness.sh        ← checks installed vs latest for all MCP tools
│   └── check-stack-freshness.ps1       ← Windows port
│
├── lib/
│   ├── feature-helpers.sh  .ps1        ← shared installer utilities (prompt, write_env_var, cron)
│   ├── notify.sh           .ps1        ← notification dispatcher (reads NOTIFY_CHANNEL)
│   ├── notify-telegram.sh  .ps1        ← Telegram backend (send pitch, poll reply, send text)
│
├── features/
│   └── stack-alerts/
│       ├── install.sh      install.ps1 ← interactive setup: Telegram creds + cron/Task Scheduler
│       └── README.md                   ← feature docs, prerequisites, uninstall
│
├── state/                              ← runtime state (gitignored except .gitkeep)
│   └── stack-alerts-pending.json       ← written by send job, deleted by poll job on reply
│
├── skills/
│   ├── prior-art-check/SKILL.md        ← MemPalace-first skill
│   └── judge/SKILL.md                  ← code-reviewer subagent gate
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
├── LICENSE                             ← MIT for the glue; upstream licenses apply to each dep
├── HANDOFF.md                          ← overnight-handoff brief + work log
├── PRD.md                              ← Ralph-driven maintenance PRD
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
│   ├── prior-art-check/                ← from step 6
│   └── judge/                          ← from step 6
├── hooks/
│   ├── langfuse_hook.py                ← Stop hook, step 8
│   ├── scan-secrets/                   ← guardrail, step 7
│   ├── scan-commit/                    ← guardrail, step 7
│   └── prompt-injection-defender/      ← guardrail, step 7
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

Windows equivalent: substitute PowerShell `Remove-Item -Recurse -Force`
and adjust paths (`$env:USERPROFILE\.claude` etc.).

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

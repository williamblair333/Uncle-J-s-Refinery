# Uncle J's Refinery

*Industrial-grade context hygiene for Claude Code.*

Uncle J's Refinery is a self-hosted, locally-installed stack that turns a
Claude Code agent into a precision instrument. Crude tokens in, refined
work out. Input tokens down ~80% via structural retrieval — code, data,
docs, memory. Output tokens down ~25-40% via prompt-level discipline.
Every turn traced to a local Langfuse. Every destructive command gated.
Every edit verified before it lands. Twelve components, one install.

**Linux-first.** Built and tested on Debian/Ubuntu. macOS works without
modification (same `.sh` scripts). Windows is supported via parallel
`.ps1` scripts, with caveats documented in [§ Windows-specific notes](#windows-specific-notes).

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

## Prerequisites

- Bash 4+ (Linux/macOS) — PowerShell 5.1+ on Windows
- Python 3.11+ (auto-installed via `uv` if missing)
- Node.js 18+ (for Context7)
- Git 2.30+
- Docker + Docker Compose plugin (for Langfuse — optional but recommended)
- ~15 GB free disk (Langfuse images are ~5 GB; Postgres/ClickHouse/MinIO grow as they run)
- Internet connection (first run pulls ~2 GB of Python/Node/Docker packages)

The installers detect missing prerequisites and either auto-install them
(where safe — e.g., `uv`) or tell you what to `apt`/`dnf`/`brew`/`winget`
and bail cleanly.

---

## Quick install

### Linux / macOS

```bash
./prerequisites.sh          # git, node, claude via your distro's package manager
./install.sh --auto-register
./verify.sh                 # expect all PASS
cp CLAUDE.md.merged ~/.claude/CLAUDE.md
./install-reliability.sh
./install-guardrails.sh
./install-langfuse.sh
```

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\prerequisites.ps1
# Close this PowerShell, open a fresh one (winget PATH propagation)
powershell -ExecutionPolicy Bypass -File .\install.ps1 -AutoRegister
.\verify.ps1
Copy-Item .\CLAUDE.md.merged "$env:USERPROFILE\.claude\CLAUDE.md" -Force
.\install-reliability.ps1
.\install-guardrails.ps1
.\install-langfuse.ps1
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
On **Arch** it uses `pacman`. On **macOS** it uses `brew`. On **Windows**
(`.ps1` version) it uses `winget`.

**Windows note:** after winget runs, close this shell and open a fresh one.
PATH changes from MSI installers don't propagate to the running process.

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
fails — the usual culprit on Windows is stale PATH; on Linux it's
usually a missing prereq that prerequisites.sh couldn't cover (rare).

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
2. Generates `.env` with random secure credentials via `scripts/generate-env.sh`
3. Runs `docker compose up -d` (pulls ~5 GB of images; first boot takes 90-120s)
4. Installs the Stop hook via `scripts/install-hook.sh`
5. Applies the v3-pin and env-patch for the hook

**Langfuse UI:** http://localhost:3050. Login with `admin@localhost.local`
and the password in `claude-code-langfuse-template/.env`
(`LANGFUSE_INIT_USER_PASSWORD`).

### 9. MCP performance tuning

Three MCP servers default to `uvx` / `npx` invocations that re-resolve
their packages on every Claude Code launch, which can blow past Claude
Code's default 30s startup timeout. Fix, once, persistently:

**Linux/macOS:**
```bash
# Raise the startup budget
echo 'export MCP_TIMEOUT=60000' >> ~/.bashrc
source ~/.bashrc

# Install as real binaries
uv tool install --from git+https://github.com/oraios/serena serena-agent
uv tool install mcp-server-motherduck
npm install -g @upstash/context7-mcp

# Re-register at installed-binary paths
claude mcp remove serena
claude mcp add -s user serena -- "$HOME/.local/bin/serena" start-mcp-server --context ide-assistant

claude mcp remove duckdb
claude mcp add -s user duckdb -- "$HOME/.local/bin/mcp-server-motherduck" --db-path :memory: --read-write --allow-switch-databases

claude mcp remove context7
claude mcp add -s user context7 -- "$(npm prefix -g)/bin/context7-mcp"

claude mcp list
```

**Windows:**
```powershell
setx MCP_TIMEOUT 60000
uv tool install --from git+https://github.com/oraios/serena serena-agent
uv tool install mcp-server-motherduck
npm install -g @upstash/context7-mcp

claude mcp remove serena
claude mcp add -s user serena -- "$env:USERPROFILE\.local\bin\serena.exe" start-mcp-server --context ide-assistant

claude mcp remove duckdb
claude mcp add -s user duckdb -- "$env:USERPROFILE\.local\bin\mcp-server-motherduck.exe" --db-path :memory: --read-write --allow-switch-databases

claude mcp remove context7
claude mcp add -s user context7 -- "$env:APPDATA\npm\context7-mcp.cmd"
```

Cold-start drops from 14-24s → 7-18s per server.

### 10. (Optional) Bootstrap MemPalace

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

(Windows: `.\ralph-harness.ps1 -PrdPath .\PRD.md -RepoPath C:\path\to\repo`)

Our harness uses the retrieval stack's verification tools
(`get_pr_risk_profile < 0.65`, `get_untested_symbols == 0`, PRD marked
DONE) as exit criteria — solves Ralph's classic failure mode of
declaring victory on a broken change. Starting template at
`prd-template.md`.

---

## Troubleshooting

### `verify.sh` / `verify.ps1` reports FAIL after fresh install

**Linux/macOS:** check `echo $PATH` and make sure `~/.local/bin` is on
it (where `uv` and the installed MCP binaries live). Add to your shell
RC if not: `export PATH="$HOME/.local/bin:$PATH"`.

**Windows:** PowerShell PATH is stale. Open a fresh window. If that
doesn't fix it, reboot — winget sometimes needs a full login to
propagate PATH changes from MSI installers.

### MCP servers show ✗ Failed to connect

Either they hit the 30s startup timeout or they're actually broken:

```bash
echo $MCP_TIMEOUT   # Linux — should be 60000
claude mcp list
```

```powershell
$env:MCP_TIMEOUT    # Windows — same expectation
claude mcp list
```

If the timeout is empty or below 60000, see step 9. If set and servers
still fail, follow step 9 to install them as real binaries and
re-register.

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
├── skills/
│   ├── prior-art-check/SKILL.md        ← MemPalace-first skill
│   └── judge/SKILL.md                  ← code-reviewer subagent gate
│
├── docs/
│   ├── STACK.md                        ← one-page-per-tool reference
│   └── RELIABILITY.md                  ← reliability-layer deep dive
│
├── mcp-clients/
│   ├── claude-code-mcp.json            ← templates for various MCP-speaking clients
│   ├── claude-desktop-config-fragment.json
│   ├── cursor-mcp.json
│   └── windsurf-mcp.json
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

Each component retains its own upstream license. This integration
(install scripts, merged CLAUDE.md, custom skills, Ralph harness) is
provided as-is.

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

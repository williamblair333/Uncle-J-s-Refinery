# Uncle J's Refinery

*Industrial-grade context hygiene for Claude Code.*

Uncle J's Refinery is a self-hosted, locally-installed stack that turns a
Claude Code agent into a precision instrument. Crude tokens in, refined
work out. Input tokens down ~80% via structural retrieval — code, data,
docs, memory. Output tokens down ~25-40% via prompt-level discipline.
Every turn traced to a local Langfuse. Every destructive command gated.
Every edit verified before it lands. Twelve components, one install.

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

Works on Windows (this repo is PowerShell-first) but the Python/Node
stack runs anywhere.

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

- Windows 10/11 with PowerShell 5.1+ (or PowerShell 7)
- ~15 GB free disk (Docker images for Langfuse alone are ~5 GB; WSL2 VHDX grows as it runs)
- Admin rights (winget installs request UAC)
- An internet connection (first run pulls ~2 GB of Python/Node/Docker packages)

If any of these are missing, the installers will tell you and bail cleanly.

---

## First-time install (fresh machine)

All commands run from `C:\Users\wblair\Downloads\claude\_stack_setup\`.

### 1. Install OS-level prerequisites

```powershell
powershell -ExecutionPolicy Bypass -File .\prerequisites.ps1
```

Installs (via winget, skips anything already present):

- `Git.Git` — needed by uvx to clone Serena
- `OpenJS.NodeJS.LTS` — needed by Context7 via npx
- `Anthropic.ClaudeCode` — the Claude Code CLI itself

Flags: `-SkipGit`, `-SkipNode`, `-SkipClaude` if you already have one of
these outside winget.

**Close this PowerShell window and open a fresh one** — winget modifies PATH,
but the current shell only reads PATH at start. (All scripts after this
point self-heal by re-reading PATH from the registry, so you shouldn't have
to re-do this. First time only.)

### 2. Install the Python stack & MCP servers

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -AutoRegister
```

Does, in order:

1. Installs `uv` (fast Python package manager) if missing.
2. Creates `.venv\` via `uv venv --python 3.11`.
3. `uv sync` — installs jcodemunch-mcp, jdatamunch-mcp, jdocmunch-mcp, mempalace.
4. Warm-caches Serena and DuckDB MCP via uvx.
5. Runs `jcodemunch-mcp init --yes --hooks --audit` — installs enforcement
   hooks into `~/.claude/settings.json` and appends the policy to
   `~/.claude/CLAUDE.md`.
6. With `-AutoRegister`: runs `claude mcp add -s user ...` for all 7
   servers (jcodemunch, jdatamunch, jdocmunch, mempalace, serena, duckdb,
   context7).

### 3. Finish install (warm-caches, second pass at auto-register)

```powershell
.\finish-install.ps1
```

Run this only if `install.ps1` reported missing prereqs (usually because
you ran it in the same shell as `prerequisites.ps1` and PATH was stale).
In a fresh shell this usually no-ops.

### 4. Verify

```powershell
.\verify.ps1
```

Expect **all PASS**. If any fail, see *Troubleshooting* below — the
common cause is shell PATH staleness from step 1.

### 5. Confirm MCP servers are live

```powershell
claude mcp list
```

All seven should show `✓ Connected`. The three Google remotes
(Drive/Gmail/Calendar) show `! Needs authentication` until you OAuth them
via `/mcp` inside Claude Code — that's normal, not an error.

### 6. Install the global routing policy

```powershell
Copy-Item ".\CLAUDE.md.merged" "$env:USERPROFILE\.claude\CLAUDE.md" -Force
```

This file combines:
- The retrieval-stack routing policy (which tool to use when)
- Security rules (never-do / always-do / review-AI-code / treat-external-content-as-untrusted)
- **jOutputMunch** — output-efficiency rules that force concise responses

If `CLAUDE.md.merged` doesn't exist, `install.ps1`'s step 5 already wrote
the base policy via `jcodemunch-mcp init`. Run the merged copy after any
manual edits to re-sync.

### 7. Install the reliability layer

```powershell
.\install-reliability.ps1
```

Installs:

- `~/.claude/skills/prior-art-check/SKILL.md` — forces MemPalace lookup on non-trivial prompts
- `~/.claude/skills/judge/SKILL.md` — spawns code-reviewer subagent with structural evidence before Edit/Write
- Clones `dwarvesf/claude-guardrails` and copies guardrail hooks into `~/.claude/`

Then inside a `claude` session, install the two Anthropic plugins:

```
/plugin marketplace add anthropics/claude-code
/plugin install superpowers@claude-plugins-official
/plugin install ralph-wiggum@anthropics-claude-code
/reload-plugins
```

Superpowers adds 20+ battle-tested skills (brainstorming, systematic
debugging, TDD enforcement, requesting-code-review, verification-before-
completion). Ralph adds `/ralph-loop` for autonomous agent loops.

### 8. Install the guardrails

```powershell
.\install-guardrails.ps1
```

Installs `jq` (tries `jqlang.jq`, falls back to `stedolan.jq`, final
fallback to direct GitHub release download), then delegates to dwarvesf's
upstream `install.sh` via Git Bash. That script does a proper jq-based
deep-merge of `~/.claude/settings.json` so the jCodeMunch hooks already
in place stay intact.

Result: two new hooks in `settings.json`:
- `UserPromptSubmit` → `scan-secrets.sh` — blocks pasted credentials
- `PostToolUse` (Read/WebFetch/Bash/mcp__.*) → `prompt-injection-defender.sh`

Plus five `PreToolUse` Bash-matcher entries that block destructive `rm`,
pipe-to-shell, direct pushes to main, exfil to webhook.site/ngrok, and
escalation flags like `--dangerously-skip-permissions`.

### 9. Install Langfuse (observability)

**First time only** — requires Docker Desktop. If you don't have it:

```powershell
.\install-langfuse.ps1
```

First run installs Docker Desktop, then tells you to launch it manually
(WSL2 backend setup needs a GUI). Wait for the whale icon in the tray to
go solid white, then re-run:

```powershell
.\install-langfuse.ps1
```

This time:

1. Clones `doneyli/claude-code-langfuse-template` into `claude-code-langfuse-template\`
2. Generates `.env` with random secure credentials via `scripts/generate-env.sh`
3. Runs `docker compose up -d` (pulls ~5 GB of images; first boot takes 90-120s)
4. Installs the Stop hook via `scripts/install-hook.sh`

**Langfuse UI:** http://localhost:3050. Login with `admin@localhost.local`
and the password in `claude-code-langfuse-template\.env`
(`LANGFUSE_INIT_USER_PASSWORD`).

#### 9a. Finalize the Stop hook (Windows-specific fixes)

The upstream `install-hook.sh` has three known gaps on Windows that you
need to patch manually on first install:

1. It fails to write the Stop hook into `settings.json` because it feeds
   Windows Python an MSYS-style `/c/Users/...` path that Python can't
   resolve.
2. `pip install langfuse` grabs v4.x, but the hook script uses the v3
   API (`start_as_current_span`).
3. Python on Windows defaults to `cp1252` when reading text files, and
   transcripts contain UTF-8.

Run these three commands to apply all three fixes:

```powershell
# Pin langfuse to v3 (has the API the hook uses)
python3.13 -m pip install --upgrade "langfuse>=3.0,<4"
```

```powershell
# Patch settings.json: add Stop hook, Langfuse env vars, PYTHONUTF8=1
@'
import json, shutil
from pathlib import Path

settings_path = Path.home() / ".claude" / "settings.json"
hook_path    = Path.home() / ".claude" / "hooks" / "langfuse_hook.py"
env_path     = Path(r"C:\Users\wblair\Downloads\claude\_stack_setup\claude-code-langfuse-template\.env")

shutil.copy(str(settings_path), str(settings_path) + ".bak.langfuse")

creds = {}
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        creds[k.strip()] = v.strip().strip('"').strip("'")

d = json.loads(settings_path.read_text())
d.setdefault("hooks", {})["Stop"] = [{
    "matcher": "",
    "hooks": [{
        "type": "command",
        "command": f'python3.13 "{hook_path.as_posix()}"'
    }]
}]
d.setdefault("env", {}).update({
    "LANGFUSE_HOST":       "http://localhost:3050",
    "LANGFUSE_PUBLIC_KEY": creds["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"],
    "LANGFUSE_SECRET_KEY": creds["LANGFUSE_INIT_PROJECT_SECRET_KEY"],
    "TRACE_TO_LANGFUSE":   "true",
    "PYTHONUTF8":          "1",
})
settings_path.write_text(json.dumps(d, indent=2))
print("OK")
'@ | Out-File -Encoding utf8 -FilePath $env:TEMP\patch_langfuse.py
python3.13 $env:TEMP\patch_langfuse.py
```

```powershell
# Ensure the state dir exists (hook writes its log there)
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\state" | Out-Null
```

Then smoke-test end-to-end:

```powershell
cd $env:TEMP
claude
# Inside claude, ask something trivial like "what is 2+2", then /quit
```

```powershell
Get-Content "$env:USERPROFILE\.claude\state\langfuse_hook.log" -Tail 10
```

You should see `[INFO] Processed N turns ... in X.Xs` at the bottom.
Refresh http://localhost:3050 → Claude Code project → Traces — your
test turn appears there within ~10 seconds.

### 10. MCP performance tuning

Three MCP servers default to `uvx` / `npx` invocations that re-resolve
their packages on every Claude Code launch, which blows past Claude
Code's default 30s startup timeout. Fix, once, persistently:

```powershell
# Raise the startup budget to 60s
setx MCP_TIMEOUT 60000

# Install serena, duckdb, and context7 as real binaries
uv tool install --from git+https://github.com/oraios/serena serena-agent
uv tool install mcp-server-motherduck
npm install -g @upstash/context7-mcp
```

Then re-register each to point at the installed binary instead of the
`uvx`/`npx` invocation:

```powershell
claude mcp remove serena
claude mcp add -s user serena -- "$env:USERPROFILE\.local\bin\serena.exe" start-mcp-server --context ide-assistant
```

```powershell
claude mcp remove duckdb
claude mcp add -s user duckdb -- "$env:USERPROFILE\.local\bin\mcp-server-motherduck.exe" --db-path :memory: --read-write --allow-switch-databases
```

```powershell
claude mcp remove context7
claude mcp add -s user context7 -- "$env:APPDATA\npm\context7-mcp.cmd"
```

```powershell
claude mcp list
```

Cold-start time drops from 14-24s → 7-18s per server. Noticeable.

### 11. (Optional) Bootstrap MemPalace

MemPalace is installed but empty. To get value, mine your project history
and Claude Code session transcripts:

```powershell
.\.venv\Scripts\mempalace.exe init C:\path\to\a\project
```

```powershell
.\.venv\Scripts\mempalace.exe mine C:\path\to\a\project
```

```powershell
.\.venv\Scripts\mempalace.exe mine $env:USERPROFILE\.claude\projects\ --mode convos
```

The last line ingests all your Claude Code sessions so `mempalace search
"why did we switch to X"` actually returns hits from day one instead of
starting cold.

---

## Daily usage

Just use Claude Code normally. The stack is global — every project, every
session, the routing policy and hooks apply automatically. You can tell
it's working when:

- Claude reaches for `search_symbols` or `get_file_outline` instead of
  `Read` on a source file
- Responses don't start with "Great question!" or end with "I hope this
  helps!"
- You see traces appear in Langfuse within seconds of each turn
- Destructive commands get blocked before they run

### Per-project customization

Add a `CLAUDE.md` to any repo root to override or extend the global policy
for that project only. Add a `.claude/settings.local.json` for
per-project MCP servers, hooks, or permissions.

### Skipping permission prompts for a folder

```powershell
New-Item -ItemType Directory -Force .claude | Out-Null
@'
{
  "permissions": {
    "defaultMode": "acceptEdits",
    "allow": ["Bash(*)", "Edit(*)", "Write(*)"]
  }
}
'@ | Set-Content .claude\settings.local.json
```

Never do this globally or in a folder containing credentials.

### Using Ralph (autonomous loop)

```powershell
.\ralph-harness.ps1 -PrdPath .\PRD.md -RepoPath C:\path\to\repo
```

Versus the vanilla `/ralph-loop` plugin, this harness uses the retrieval
stack's verification tools (`get_pr_risk_profile < 0.65`,
`get_untested_symbols == 0`, and PRD marked DONE) as exit criteria —
solves Ralph's classic failure mode of declaring victory on a broken
change. Starting template at `prd-template.md`.

---

## Troubleshooting

### `verify.ps1` reports most things FAIL after a fresh install

Your PowerShell session's PATH is stale. Close it, open a new window,
re-run `.\verify.ps1`. If that doesn't fix it, reboot once — winget
sometimes needs a full login to propagate PATH changes.

### MCP servers show ✗ Failed to connect

Either they hit the 30s startup timeout or they're actually broken. Check:

```powershell
$env:MCP_TIMEOUT
claude mcp list
```

If `MCP_TIMEOUT` is empty or less than 60000, re-run `setx MCP_TIMEOUT
60000` and restart Claude Code. If timeout is set and servers still fail,
follow step 10 above — install them as real binaries and re-register.

### Langfuse UI is at localhost:3050 but traces don't appear

Check the hook log:

```powershell
Get-Content "$env:USERPROFILE\.claude\state\langfuse_hook.log" -Tail 30
```

Common failures:
- `UnicodeDecodeError ... cp1252` → `PYTHONUTF8=1` missing from
  `settings.json` env block. Re-run step 9a.
- `'Langfuse' object has no attribute 'start_as_current_span'` → langfuse
  SDK is v4+. Downgrade: `python3.13 -m pip install "langfuse>=3.0,<4"`
- `Langfuse API keys not set` → env block in `settings.json` doesn't
  have `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`. Re-run step 9a.
- Empty log, hook dir doesn't exist → state dir missing:
  `New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\state"`

### Langfuse containers fail to start (`dependency failed to start`)

MinIO, Postgres, or ClickHouse failed health check. Usually disk pressure.
Check:

```powershell
Get-PSDrive C | Select-Object Used,Free
docker system df
```

If C: has less than 10 GB free, point Docker Desktop at a different drive
(Settings → Resources → Advanced → Disk image location), then:

```powershell
cd C:\Users\wblair\Downloads\claude\_stack_setup\claude-code-langfuse-template
docker compose down -v
docker compose up -d
```

The `-v` drops the half-initialized volumes so they recreate cleanly.

### Claude Code keeps asking for permissions

See the "Skipping permission prompts for a folder" section above. Or for
a single session: `claude --dangerously-skip-permissions`. Or use
`/permissions` inside a session for interactive editing.

### jOutputMunch rules aren't taking effect

The rules live in `~/.claude/CLAUDE.md`. Verify they're there:

```powershell
Select-String "jOutputMunch" "$env:USERPROFILE\.claude\CLAUDE.md"
```

If missing, re-run step 6 (`Copy-Item .\CLAUDE.md.merged ...`).

### Something is broken, I want to reset and try again

```powershell
# Back up first
Copy-Item "$env:USERPROFILE\.claude" "$env:USERPROFILE\.claude.bak.$(Get-Date -Format yyyyMMdd-HHmmss)" -Recurse -Force

# Stop Langfuse
cd C:\Users\wblair\Downloads\claude\_stack_setup\claude-code-langfuse-template
docker compose down -v

# Remove MCP registrations
foreach ($s in "jcodemunch","jdatamunch","jdocmunch","mempalace","serena","duckdb","context7") {
    claude mcp remove $s 2>$null
}

# Remove venv
cd C:\Users\wblair\Downloads\claude\_stack_setup
Remove-Item -Recurse -Force .venv, .venv-test -ErrorAction SilentlyContinue
```

Then re-run from step 2.

---

## File map

```
_stack_setup\
├── README.md                           ← this file
├── CLAUDE.md                           ← base routing policy (gets overwritten by jcodemunch init)
├── CLAUDE.md.merged                    ← full policy: routing + security + jOutputMunch (copy to ~/.claude/)
├── AGENTS.md                           ← agent-facing policy mirror (written by jcodemunch init)
├── pyproject.toml                      ← uv-managed Python deps (jcodemunch, jdatamunch, jdocmunch, mempalace)
├── uv.lock
├── .venv\                              ← real Python 3.11 venv created by install.ps1
│
├── install.ps1                         ← step 2: Python stack + MCP registration
├── install.sh                          ← Linux/macOS equivalent
├── prerequisites.ps1                   ← step 1: git/node/claude via winget
├── finish-install.ps1                  ← step 3: re-attempt after PATH refresh
├── install-reliability.ps1             ← step 7: prior-art-check + judge + guardrails clone
├── install-guardrails.ps1              ← step 8: dwarvesf guardrails via Git Bash
├── install-langfuse.ps1                ← step 9: Docker + Langfuse + hook
├── ralph-harness.ps1                   ← verification-gated Ralph loop wrapper
├── prd-template.md                     ← starting template for Ralph tasks
├── verify.ps1 / verify.sh              ← step 4: all-pass sanity check
│
├── skills\
│   ├── prior-art-check\SKILL.md        ← forces MemPalace lookup (copied to ~/.claude/skills/)
│   └── judge\SKILL.md                  ← code-reviewer subagent gate (copied to ~/.claude/skills/)
│
├── docs\
│   ├── STACK.md                        ← one-page-per-tool reference
│   └── RELIABILITY.md                  ← reliability-layer deep dive
│
├── claude-guardrails\                  ← cloned dwarvesf/claude-guardrails (don't edit; re-clone to update)
│   ├── install.sh                      ← called by install-guardrails.ps1
│   ├── full\                           ← secret scanner + injection defender (the version installed)
│   └── lite\                           ← simpler variant, not used by default
│
└── claude-code-langfuse-template\      ← cloned doneyli/claude-code-langfuse-template
    ├── .env                            ← auto-generated credentials; git-ignored
    ├── docker-compose.yml              ← Langfuse stack (postgres, clickhouse, redis, minio, langfuse-web, langfuse-worker)
    └── scripts\
        ├── generate-env.sh             ← regenerates .env with fresh random secrets
        ├── install-hook.sh             ← installs langfuse_hook.py (Windows patches in step 9a above)
        └── analyze-traces.sh           ← sample trace analysis against the self-hosted Langfuse
```

Sibling folders (outside `_stack_setup`, under `C:\Users\wblair\Downloads\claude\`):

```
claude\
├── jcodemunch-mcp-main\                ← source archive; the pip package is what runs
├── jdatamunch-mcp-master\              ← source archive
├── jdocmunch-mcp-master\               ← source archive
├── mempalace-develop\                  ← source archive
└── jOutputMunch-master\                ← rules + guides; integrated into ~/.claude/CLAUDE.md (step 6)
```

---

## What lives where after install

```
C:\Users\wblair\.claude\
├── CLAUDE.md                           ← routing policy + security + jOutputMunch (from step 6)
├── settings.json                       ← hooks, env vars (LANGFUSE_*, PYTHONUTF8, TRACE_TO_LANGFUSE), permissions.deny
├── .claude.json                        ← MCP server registrations (managed by `claude mcp add/remove`)
├── skills\
│   ├── prior-art-check\                ← custom, from step 7
│   └── judge\                          ← custom, from step 7
├── hooks\
│   ├── langfuse_hook.py                ← Stop hook, installed in step 9
│   ├── scan-secrets\                   ← guardrail, installed in step 8
│   ├── scan-commit\                    ← guardrail, installed in step 8
│   └── prompt-injection-defender\      ← guardrail, installed in step 8
├── state\
│   ├── langfuse_hook.log               ← hook activity log
│   ├── langfuse_state.json             ← per-session processed-line tracking
│   └── pending_traces.jsonl            ← queued traces when Langfuse is down
├── projects\                           ← Claude Code session transcripts (per-project)
└── logs\
    └── permission-events.jsonl         ← flagged permission events (consumed by langfuse hook)
```

---

## Provenance

Each tool's canonical source:

| Tool | Origin |
| --- | --- |
| jCodeMunch / jDataMunch / jDocMunch | [@jgravelle](https://github.com/jgravelle) |
| MemPalace | [mempalaceofficial.com](https://mempalaceofficial.com) |
| Serena | [oraios/serena](https://github.com/oraios/serena) |
| DuckDB MCP | [motherduckdb/mcp-server-motherduck](https://github.com/motherduckdb/mcp-server-motherduck) |
| Context7 | [@upstash/context7-mcp](https://www.npmjs.com/package/@upstash/context7-mcp) |
| jOutputMunch | [@jgravelle](https://github.com/jgravelle) — rules-only, no code |
| Superpowers | [obra/superpowers](https://github.com/obra/superpowers), adopted into Anthropic's official marketplace |
| Ralph Wiggum | [Anthropic claude-code marketplace](https://github.com/anthropics/claude-code) |
| Claude Guardrails | [dwarvesf/claude-guardrails](https://github.com/dwarvesf/claude-guardrails) |
| Langfuse template | [doneyli/claude-code-langfuse-template](https://github.com/doneyli/claude-code-langfuse-template) |

---

## Lessons learned (for future maintainers)

These are real failures encountered during install. Recording them here so
the next person doesn't repeat them.

**Windows PATH propagation.** winget adds things to PATH but the current
shell doesn't see them. Open a new shell. If that's not enough, reboot.
The installers self-heal by reading PATH from the registry — but that
only works for tools they launch, not for you typing commands.

**Docker Desktop + disk space.** First-run `docker compose up -d` for
Langfuse pulls ~5 GB of images. If C: is tight, the pull silently
corrupts volumes during init and dependency containers go unhealthy
forever. Ensure 15 GB free *before* starting, or relocate Docker's disk
image in Docker Desktop settings.

**Langfuse SDK version drift.** `pip install langfuse` without a pin
grabs v4+, which removed the `start_as_current_span` method the hook
uses. Always pin `"langfuse>=3.0,<4"` when installing or upgrading.

**Windows Python default encoding.** Python on Windows reads text files
as cp1252 unless told otherwise. Claude Code transcripts contain UTF-8.
Set `PYTHONUTF8=1` in the `settings.json` env block so the hook can
read its own inputs.

**`cmd /c` wrapper for npx MCP servers.** `claude mcp add -s user foo
-- npx -y something` works at registration but trips `/doctor` because
Windows can't invoke `.cmd` shims from spawned processes. Either wrap
with `cmd /c` or install the tool as a real binary and point at it
directly — the latter is faster and avoids the warning entirely.

**MCP 30s startup timeout.** `uvx`/`npx` MCP entries re-resolve packages
on every launch. On slow networks or cold caches, that blows the 30s
budget. `setx MCP_TIMEOUT 60000` + pre-installing the binaries is the
fix. Don't just raise the timeout and call it done — a 60s cold start
on every session is user-hostile.

**Permissions deny editing settings.json.** Claude Code can't edit its
own `settings.json` because it's in the `permissions.deny` list. Edit
from PowerShell (or any process outside Claude Code) — that's by design,
to prevent a session from escalating its own permissions.

**MemPalace registration needs the Python module, not the CLI.**
`mempalace mcp` just prints instructions. The real server is
`python -m mempalace.mcp_server`. Use the full invocation in
`claude mcp add`.

**Ralph marketplace name.** Ralph Wiggum is in the
`anthropics-claude-code` marketplace (from `/plugin marketplace add
anthropics/claude-code`), NOT `claude-plugins-official`. The latter
only has Superpowers.

**jq winget package rename.** `stedolan.jq` became `jqlang.jq`. The
guardrails installer tries both, with a final fallback to downloading
`jq.exe` directly from the jqlang GitHub releases into `~/.local/bin`.

---

## Uninstall

```powershell
# Stop Langfuse and drop its data
cd C:\Users\wblair\Downloads\claude\_stack_setup\claude-code-langfuse-template
docker compose down -v
```

```powershell
# Remove MCP registrations
foreach ($s in "jcodemunch","jdatamunch","jdocmunch","mempalace","serena","duckdb","context7") {
    claude mcp remove $s 2>$null
}
```

```powershell
# Remove uv tool installs and npm globals
uv tool uninstall serena-agent mcp-server-motherduck
npm uninstall -g @upstash/context7-mcp
```

```powershell
# Back up user config, then wipe stack-specific bits
Copy-Item "$env:USERPROFILE\.claude" "$env:USERPROFILE\.claude.bak" -Recurse -Force
Remove-Item -Recurse -Force "$env:USERPROFILE\.claude\hooks"
Remove-Item -Recurse -Force "$env:USERPROFILE\.claude\skills\prior-art-check"
Remove-Item -Recurse -Force "$env:USERPROFILE\.claude\skills\judge"
Remove-Item "$env:USERPROFILE\.claude\CLAUDE.md"
```

`settings.json` needs surgical editing — delete the LANGFUSE/TRACE_TO/
PYTHONUTF8 keys from the `env` block, remove the `Stop` hook entry, and
clear the jCodeMunch/guardrails entries from `hooks` if you don't want
them anymore. Or just reset to `{}` if you want a clean slate.

```powershell
# Remove the stack folder itself
Remove-Item -Recurse -Force C:\Users\wblair\Downloads\claude\_stack_setup
```

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
Ralph harness, the prior-art-check and judge skills, the Windows
install patches, this README — is integration glue. The hard work was
done upstream.

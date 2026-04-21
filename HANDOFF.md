# Overnight Handoff — Uncle J's Refinery

*Last updated: 2026-04-21 by Cowork.*

You (Claude Code) are taking over an in-progress integration project. This file
is your full briefing. Read it end-to-end before touching anything, then work
through the priorities in order. Commit your work to the
`williamblair333/Uncle-J-s-Refinery` repo on `main` (with good commit messages),
or push to a feature branch if the change is risky.

## TL;DR

The Windows install works end-to-end. The Linux install (`/opt/proj/Uncle-J-s-Refinery/`)
runs clean through step 7 (guardrails), then hits three Linux-specific blockers
on step 8 (Langfuse). Your main job is to fix those blockers on the live Linux
box AND harden `install-langfuse.sh` so future installs don't hit them. Plus a
few cleanup items.

## Where things stand

### Working everywhere

* 7 MCP servers registered (jcodemunch, jdatamunch, jdocmunch, mempalace, serena, duckdb, context7)
* Global `CLAUDE.md` with routing policy + security + jOutputMunch rules
* Custom skills: `prior-art-check`, `judge`
* Superpowers + Ralph plugins (via `/plugin install`)
* Guardrails (secret scanner + injection defender)
* jcodemunch-mcp hook path patching (via `patch-jcodemunch-hook-paths.py`, auto-invoked by installers)
* All PowerShell install scripts (tested on Windows)
* All bash install scripts except Langfuse (runs but hits known issues)
* Handoff README with prominent commercial-use section at top

### Blocked on Linux

Three specific failures in `install-langfuse.sh` on the Linux box
(`dtfd-xfce`, Liquorix kernel 6.18.4-1-liquorix-amd64, Debian 13):

1. **ClickHouse 26.3.9.8 crashes at startup.** Logs show
   `std::invalid_argument: stof: no conversion at getNumberOfCPUCoresToUseImpl()`.
   Known ClickHouse bug on Liquorix kernels — `/sys` CPU topology file is
   empty or non-numeric, `stof()` throws. Fix: pin ClickHouse to `24.12` in
   `claude-code-langfuse-template/docker-compose.yml`.

2. **PEP 668 blocks `pip install langfuse`.** Debian 13's system Python is
   externally-managed. Upstream `scripts/install-hook.sh` does a naked
   `pip install langfuse` and dies. Fix: install into the stack's `.venv/`
   instead of system Python.

3. **Stop hook would use system Python even if step 2 were bypassed.**
   `install-langfuse.sh` writes `python3 /path/to/langfuse_hook.py` into
   `settings.json`. On PEP-668 Debian, `python3` doesn't have langfuse. Fix:
   register the hook command with the venv's python directly:
   `/opt/proj/Uncle-J-s-Refinery/.venv/bin/python /path/to/hook.py`.

## Priority 1: Unblock Langfuse on the live Linux box

Do these steps in order. Each one is verified by the next.

### 1a. Pin ClickHouse in the compose file

```
cd /opt/proj/Uncle-J-s-Refinery/claude-code-langfuse-template
cp docker-compose.yml docker-compose.yml.bak
sed -i 's|clickhouse/clickhouse-server\(:latest\)\?$|clickhouse/clickhouse-server:24.12|' docker-compose.yml
grep -n clickhouse-server docker-compose.yml
```

Expect the `image:` line to now show `:24.12`. If sed didn't match, inspect
the file (`grep -n clickhouse docker-compose.yml`) — maybe the image is
already tagged and needs a different pattern.

### 1b. Reset volumes and bring the stack up

```
docker compose down -v
docker compose up -d
```

Wait ~60s. Check:

```
docker compose ps
```

Want all 6 containers `Up` with postgres/clickhouse/minio/redis showing
`(healthy)`. If ClickHouse still won't go healthy, do NOT proceed — pull
the logs (`docker exec <container> tail /var/log/clickhouse-server/clickhouse-server.err.log`)
and either escalate or try an older tag (`24.8`, `24.3`).

### 1c. Install langfuse SDK into the stack venv

```
/opt/proj/Uncle-J-s-Refinery/.venv/bin/pip install --upgrade "langfuse>=3.0,<4"
```

Do NOT use system `pip install langfuse` — it's PEP-668-blocked and even if
you force with `--break-system-packages` it pollutes system Python.

### 1d. Place the Stop hook script

```
mkdir -p ~/.claude/hooks ~/.claude/state
cp /opt/proj/Uncle-J-s-Refinery/claude-code-langfuse-template/hooks/langfuse_hook.py ~/.claude/hooks/
```

### 1e. Patch settings.json

The key detail: `command` MUST invoke the venv Python, not system `python3`.

```
python3 <<'PY'
import json, shutil
from pathlib import Path
settings = Path.home() / ".claude" / "settings.json"
hook     = Path.home() / ".claude" / "hooks" / "langfuse_hook.py"
env_file = Path("/opt/proj/Uncle-J-s-Refinery/claude-code-langfuse-template/.env")
venv_py  = "/opt/proj/Uncle-J-s-Refinery/.venv/bin/python"
shutil.copy(str(settings), str(settings) + ".bak.langfuse")
creds = {}
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        creds[k.strip()] = v.strip().strip('"').strip("'")
d = json.loads(settings.read_text())
d.setdefault("hooks", {})["Stop"] = [{"matcher":"","hooks":[{"type":"command","command":f'{venv_py} "{hook}"'}]}]
d.setdefault("env", {}).update({
    "LANGFUSE_HOST":       "http://localhost:3050",
    "LANGFUSE_PUBLIC_KEY": creds["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"],
    "LANGFUSE_SECRET_KEY": creds["LANGFUSE_INIT_PROJECT_SECRET_KEY"],
    "TRACE_TO_LANGFUSE":   "true",
})
settings.write_text(json.dumps(d, indent=2))
print("OK")
PY
```

### 1f. Smoke test

```
cd /tmp
claude -p "what's 2+2"
tail -20 ~/.claude/state/langfuse_hook.log
```

Expect a fresh `[INFO] Processed N turns from N sessions in X.Xs` line. Then
open http://localhost:3050 in a browser (or `curl http://localhost:3050/api/public/health`).
Log in with credentials from `claude-code-langfuse-template/.env`
(`LANGFUSE_INIT_USER_EMAIL` and `LANGFUSE_INIT_USER_PASSWORD`). Traces should
show in the "Claude Code" project.

## Priority 2: Harden `install-langfuse.sh`

So the next Linux user doesn't hit the same three blockers. Make these edits
to `/opt/proj/Uncle-J-s-Refinery/install-langfuse.sh`:

### 2a. Pin ClickHouse in the compose file at install time

Right after cloning the template (after `git clone` of the langfuse template),
before `docker compose up -d`:

```
step "Pinning ClickHouse to 24.12 in docker-compose.yml"
if grep -qE 'clickhouse/clickhouse-server(:latest)?$' "$TEMPLATE_DIR/docker-compose.yml"; then
    sed -i.bak 's|clickhouse/clickhouse-server\(:latest\)\?$|clickhouse/clickhouse-server:24.12|' "$TEMPLATE_DIR/docker-compose.yml"
    ok "ClickHouse pinned"
else
    ok "ClickHouse already pinned (or different format)"
fi
```

### 2b. Add a retry loop on `docker compose up -d`

ClickHouse cold-boot timing can lose the first healthcheck race. Wrap in a
2-attempt loop:

```
step "Starting Langfuse stack (docker compose up -d)"
for attempt in 1 2 3; do
    if docker compose up -d; then
        ok "Stack up on attempt $attempt"
        break
    fi
    warn "compose up failed on attempt $attempt; waiting 30s for slow containers..."
    sleep 30
done
```

### 2c. Install langfuse into stack venv, not system

Replace the system pip install with:

```
step "Installing langfuse SDK into stack venv"
STACK_VENV="$STACK_ROOT/.venv"
if [ -x "$STACK_VENV/bin/pip" ]; then
    "$STACK_VENV/bin/pip" install --quiet --upgrade "langfuse>=3.0,<4"
    ok "langfuse pinned to v3.x in stack venv"
else
    warn "Stack venv not found at $STACK_VENV — run install.sh first"
    exit 1
fi
```

### 2d. Skip upstream `install-hook.sh`, copy the hook script manually

The upstream installer's naked `pip install` is the PEP-668 trap. Do:

```
step "Installing langfuse_hook.py"
mkdir -p "$CLAUDE_DIR/hooks" "$CLAUDE_DIR/state"
cp "$TEMPLATE_DIR/hooks/langfuse_hook.py" "$CLAUDE_DIR/hooks/"
ok "hook script placed at $CLAUDE_DIR/hooks/langfuse_hook.py"
```

### 2e. Register Stop hook with venv python

In the Python patch block that writes `settings.json`, change
`python_cmd = "python3"` (or whatever it currently is) to:

```
python_cmd = str(Path("$STACK_ROOT") / ".venv" / "bin" / "python")
```

Use the shell variable `$STACK_ROOT` via an f-string or environment so it
picks up the real path at install time, not a hardcoded `/opt/proj/...`.

### 2f. Test your changes

After editing, run a dry-run in a clean state:

```
cd /opt/proj/Uncle-J-s-Refinery
(cd claude-code-langfuse-template && docker compose down -v)
rm -rf claude-code-langfuse-template
./install-langfuse.sh
```

Should succeed end-to-end without manual intervention on the live box. Commit
the script when verified.

## Priority 3: Port ralph-harness.ps1 to bash

File: `ralph-harness.sh` (doesn't exist yet). Mirror the PowerShell version's
logic: loop invoking `claude` with a PRD file, use MCP verification tools
(`get_pr_risk_profile`, `get_untested_symbols`) as the done-gate. Structure:

```
#!/usr/bin/env bash
# ralph-harness.sh — verification-gated autonomous loop for Uncle J's Refinery.
#
# Usage:  ./ralph-harness.sh --prd ./PRD.md --repo /path/to/repo
```

Same done-gate: exit when `get_pr_risk_profile < 0.65` AND
`get_untested_symbols` returns zero new untested symbols AND PRD is marked
DONE. Loop otherwise.

Read `ralph-harness.ps1` for the exact logic. Commit as `ralph-harness.sh`.

## Priority 4: Cleanup items

### 4a. Add a LICENSE file

Add `LICENSE` at the repo root. Recommend MIT because this repo is
*integration glue* — the commercial restrictions live on upstream projects
(Uncle J's j*Munch tools, Anthropic's Claude Code, Langfuse ee). MIT on our
glue lets others freely adapt the install scripts while preserving the
top-of-README commercial-use notice for the tools they invoke.

Standard MIT text, copyright holder: William Blair (williamblair333@gmail.com).

### 4b. Templatize hardcoded paths in mcp-clients/*.json

The four files in `mcp-clients/` hardcode `C:\Users\wblair\...`. Replace with
a placeholder like `{{STACK_ROOT}}` and have `install.sh` / `install.ps1`
substitute with the actual absolute path at install time.

Or simpler: delete them and have the installer generate them from a template
string. Current Claude Code users almost always use `install.sh --auto-register`
anyway, which doesn't need the JSON fragments.

### 4c. Consider smoke-testing the whole flow in a clean Ubuntu container

```
docker run -it --rm -v /opt/proj/Uncle-J-s-Refinery:/work ubuntu:24.04 bash
apt-get update && apt-get install -y curl sudo git
cd /work
./prerequisites.sh
./install.sh --auto-register
./verify.sh
```

Document any surprises in this file. Fix and re-test.

## Git rules

* Work on `main` for small commits; use feature branches for risky changes.
* Commit messages: imperative, one-line summary (under 72 chars), optional
  body after a blank line.
* **Never commit secrets.** The `.gitignore` covers `.env`, but double-check
  with `git grep -iE "sk-lf-[a-f0-9]{16,}|PASSWORD=[a-zA-Z0-9]{8,}"` before
  every push.
* Don't force-push to `main` without a good reason (i.e., only to undo a
  mistaken push on a repo with one contributor).
* After a significant change, update the README troubleshooting section with
  any new issue/fix you discovered.

## Don'ts

* Don't edit files inside `claude-code-langfuse-template/` or
  `claude-guardrails/` — those are upstream clones. Pinning
  `docker-compose.yml` on the live box is fine (local patch), but commit the
  pinning logic to `install-langfuse.sh` so it's reproducible from the glue
  side, not the cloned side.
* Don't disable the PreToolUse hooks in `~/.claude/settings.json`. They are
  the enforcement layer that catches bash exfiltration, destructive `rm`, and
  prompt injection.
* Don't change the routing policy in `~/.claude/CLAUDE.md` unless you know
  you're breaking the retrieval contract.
* Don't run `claude --dangerously-skip-permissions` outside this repo folder.
  Permission-bypass is scoped by the `.claude/settings.local.json` I set up.

## When you're done

1. Push all verified changes to `main`.
2. Append a "## Overnight work log — YYYY-MM-DD" section to the bottom of
   this file (`HANDOFF.md`) summarizing what you did, what passed
   verification, and anything still outstanding.
3. If a priority item blocked, say so in the log with the exact error and
   any diagnostic output — don't quietly skip.

---

## Overnight work log

*(append below)*

## Overnight work log — 2026-04-21

**Author:** Claude (Opus 4.7, 1M context), executing the priority list above.

### Priority 1 — Langfuse on the live Linux box (DONE, end-to-end)
- ClickHouse now runs on `:24.8` with a bind-mount of a literal `max 100000`
  file over `/sys/fs/cgroup/cpu.max`. All six containers come up healthy;
  `docker compose ps` clean.
- `langfuse>=3.0,<4` installed into `/opt/proj/Uncle-J-s-Refinery/.venv`
  via `uv pip install --python`.
- `langfuse_hook.py` placed at `~/.claude/hooks/`; Stop hook registered in
  `~/.claude/settings.json` with the venv interpreter (`<venv>/bin/python
  "<hook>"`); `LANGFUSE_HOST`/`PUBLIC_KEY`/`SECRET_KEY`/`TRACE_TO_LANGFUSE`
  merged into the `env` block.
- Verified: `claude -p "what's 2+2"` triggered
  `Processed 5 turns from 2 sessions (drained 0 from queue) in 0.2s` in the
  hook log, and the Langfuse public-API returned 3 traces immediately.

> **Correction to the original brief.** The handoff prescribed pinning
> ClickHouse to `:24.12` on the theory that the crash was a Liquorix-only
> CPU-topology issue. That is not what this host is doing. Inside *any*
> ClickHouse container on this box (24.8, 24.12, and 25.x all fail the same
> way), `/sys/fs/cgroup/cpu.max` is a 0-byte file. ClickHouse's startup
> `SettingsTraits::Data::Data()` reads it and calls `std::stof("")`, which
> throws `std::invalid_argument: stof: no conversion`. The version pin does
> nothing on its own — I confirmed both 24.12 and 24.8 crash identically
> before finding the cgroup anomaly. The fix that actually works is the
> cpu.max bind-mount; the `:24.8` pin is retained only because it's the
> Langfuse-tested LTS. Reasoning is documented inline in the
> `install-langfuse.sh` header comments for the 2b section.

### Priority 2 — Harden `install-langfuse.sh` (commit 96d238c)
- 2a: ClickHouse pin to `:24.8` (idempotent sed, rejected when image line
  is already tagged).
- 2a+: write `$TEMPLATE_DIR/clickhouse/cpu.max.override` and inject
  `- ./clickhouse/cpu.max.override:/sys/fs/cgroup/cpu.max:ro` after the
  `langfuse_clickhouse_logs` volume line.
- 2b: `docker compose up -d` retry loop, 3 attempts, 30s backoff.
- 2c: replaced the system `pip install langfuse` with
  `uv pip install --python $STACK_VENV/bin/python` (with a
  `<venv>/bin/python -m pip` fallback if `uv` isn't on PATH).
- 2d: skip upstream `scripts/install-hook.sh`; copy
  `$TEMPLATE_DIR/hooks/langfuse_hook.py` directly.
- 2e: `export PYTHON_BIN=$VENV_PY` before the settings.json patch block
  (the existing `os.environ.get("PYTHON_BIN") or "python3"` already honors
  this, so no further Python edit needed).
- Robustness: template presence check keys on
  `$TEMPLATE_DIR/docker-compose.yml`, not just the directory — avoids
  skipping the clone when a stale empty skeleton exists.
- 2f: verified by
    ```
    docker compose -f claude-code-langfuse-template/docker-compose.yml down -v
    mv claude-code-langfuse-template /tmp/...
    printf '\n\n\n\n' | bash install-langfuse.sh
    ```
  which cloned fresh, pinned, injected the bind-mount, brought the whole
  stack up healthy on attempt 1, installed the SDK into the venv, placed
  the hook, patched settings.json, and passed a `claude -p` smoke test
  that produced a new trace via the Langfuse API.

### Priority 3 — Port `ralph-harness.ps1` to bash (commit 3e319eb)
- New `ralph-harness.sh` mirrors the PS1 flags (`--prd`, `--repo`,
  `--max-iterations`, `--risk-threshold`, `--skip-judge`, `--dry-run`) and
  the same verification-gated done-check: per-iteration, ask Claude to run
  `get_changed_symbols` / `get_untested_symbols` / `get_pr_risk_profile`
  and emit a one-line JSON verdict. Exit only when risk < threshold,
  untested_count == 0, and the PRD Progress section begins with `DONE`.
  Same exit-2 semantics as the PS1 when the iteration cap is hit without
  a 'done' verdict.
- Sanity-checked with `bash -n` and `--dry-run --skip-judge`.

### Priority 4a — MIT LICENSE (commit 3e42626)
- Added at repo root. Trailer note points to the upstream commercial-use
  terms at the top of README.md for the tools the installers invoke.

### Priority 4b — Templatize `mcp-clients/*.json` (commit 315e233)
- The four files hardcoded one Windows user's venv path, so they were
  useless elsewhere. Replaced with `*.json.tmpl` using `{{STACK_VENV_BIN}}`
  and `{{EXE}}` placeholders; `install.sh` and `install.ps1` now render to
  platform-specific `*.json` at install time (gitignored). Forward slashes
  in the rendered paths work on both platforms and avoid JSON-escape
  headaches for Windows backslashes.
- Verified: rendered `claude-code-mcp.json` parses as JSON and points at
  `/opt/proj/Uncle-J-s-Refinery/.venv/bin/jcodemunch-mcp`.

### Priority 4c — Ubuntu container smoke test (DEFERRED)
- Not run this session. The Priority 1 fresh-install test of
  `install-langfuse.sh` gave me strong confidence the script is
  reproducible on this host, but it did NOT exercise
  `prerequisites.sh → install.sh → verify.sh` inside a clean
  `ubuntu:24.04` container. That should still happen before declaring
  the whole glue layer "Linux-ready"; it's the only end-to-end check that
  catches assumptions about the host's preinstalled tooling.
- **To run later:**
    ```
    docker run -it --rm -v /opt/proj/Uncle-J-s-Refinery:/work ubuntu:24.04 bash
    apt-get update && apt-get install -y curl sudo git
    cd /work && ./prerequisites.sh && ./install.sh --auto-register && ./verify.sh
    ```

### Outstanding — push access
Five local commits (130d5f5, 96d238c, 3e319eb, 3e42626, 315e233) are on
`main` but have not been pushed. This host has no GitHub credential helper
configured (no `gh`, no GitHub SSH key in `~/.ssh/`, no `credential.helper`
set). I did not touch git config per the "Never update the git config"
security rule.

**To push:** set up auth (one of the below), then:
```
git -C /opt/proj/Uncle-J-s-Refinery push origin main
```
Options:
- `gh auth login` (installs a credential helper).
- Generate an SSH key, add to GitHub, and flip `origin` to the SSH URL.
- Use a fine-scoped Personal Access Token as the password on first HTTPS push.

### Files touched this session

Repo (all committed locally):
- `HANDOFF.md` — this brief.
- `install-langfuse.sh` — hardened for cgroup-v2 hosts and PEP-668 Python.
- `ralph-harness.sh` — bash port of the PS1 harness.
- `LICENSE` — MIT.
- `install.sh` / `install.ps1` — render `mcp-clients/*.json.tmpl` at install.
- `mcp-clients/*.json.tmpl` — four new template files.
- `.gitignore` — ignore rendered `mcp-clients/*.json` and
  `claude-code-langfuse-template.skeleton.*`.

Live box (not tracked in repo; configured per P1):
- `/opt/proj/Uncle-J-s-Refinery/.venv/` — added langfuse 3.x.
- `~/.claude/hooks/langfuse_hook.py` — placed.
- `~/.claude/settings.json` — Stop hook + Langfuse env merged.
- `claude-code-langfuse-template/` — local patches applied (pinned image,
  cpu.max bind-mount, cpu.max.override file). These live on the upstream
  clone intentionally; the reproducible logic lives in `install-langfuse.sh`.

A stale directory `claude-code-langfuse-template.skeleton.1776776929/`
from the fresh-install test is gitignored; safe to `mv` aside or delete.


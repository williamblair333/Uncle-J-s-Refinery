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

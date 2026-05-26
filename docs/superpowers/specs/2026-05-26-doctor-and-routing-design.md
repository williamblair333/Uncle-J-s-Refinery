# Design: refinery doctor + Telegram multi-agent routing

*Date: 2026-05-26 | Status: approved | Inspired by: OpenClaw competitive analysis*

---

## Feature 1 — `scripts/refinery-doctor.sh`

### What it is

A standalone script focused exclusively on **config schema drift** — `.env` var renames, stale MCP registration scopes, `~/.claude/CLAUDE.md` sync gaps, and placeholder values. Distinct from `healthcheck.sh` (runtime health) and `healthcheck.sh --fixall` (runtime repair). Doctor = config, healthcheck = runtime.

### Interface

```bash
bash scripts/refinery-doctor.sh          # dry-run: report only
bash scripts/refinery-doctor.sh --fix    # apply all auto-fixable migrations
bash scripts/refinery-doctor.sh --check embed-model   # run one check by name
```

### Output format

Mirrors `healthcheck.sh` label style:

```
==> embed-model — JCODEMUNCH_EMBED_MODEL in .env
    OK  already set

==> jcodemunch-scope — jcodemunch MCP registration scope
    MIGRATION AVAILABLE  jcodemunch registered at project scope (uvx shadow)
        fix: claude mcp remove jcodemunch -s project

DOCTOR: 1 migration available (run --fix to apply)
```

Exit codes: `0` = all clean, `1` = pending migrations.

### Day-1 migration catalog

| Check name | Detects | Auto-fixable |
|---|---|---|
| `embed-model` | `JCODEMUNCH_EMBED_MODEL` missing from `.env` | Yes — appends key pointing at discovered model path |
| `jcodemunch-scope` | jcodemunch registered at `local` or `project` scope | Yes — runs `claude mcp remove` to clear stale registrations |
| `claude-md-sync` | `~/.claude/CLAUDE.md` checksum differs from repo `CLAUDE.md` | Yes — backs up to `~/.claude/CLAUDE.md.bak`, overwrites with repo copy |
| `env-placeholders` | `.env` contains template placeholder values (e.g. `your-token-here`) | No — reports only, needs real values |

### Data integrity (pre-mortem R3)

`--fix` MUST use atomic writes for `.env`:
1. Create `.env.bak` before any mutation
2. Write changes to `.env.tmp`
3. `os.replace(".env.tmp", ".env")` — atomic on same filesystem
4. Report backup path in output

---

## Feature 2 — Telegram multi-agent routing

### What it is

A prefix-based routing layer in `telegram-gateway-poll.sh` that dispatches messages to different agent configs. Configured via `config/telegram-agents.toml`.

### New file: `config/telegram-agents.toml`

```toml
# Agents are matched in order. First prefix match wins.
# The catch-all (empty prefix) MUST be last — startup validation enforces this.
# cwd values: use "." to mean PROJ_ROOT (resolved at runtime), "/tmp" for isolated.

[[agents]]
name   = "work"
prefix = "/work"
cwd    = "."           # resolved to PROJ_ROOT at runtime
system_prompt = ""     # empty = no override; project CLAUDE.md loads normally

[[agents]]
name   = "default"
prefix = ""            # catch-all — must be last
cwd    = "/tmp"
system_prompt = "restricted"   # sentinel → TELEGRAM_SYSTEM_RESTRICTION string
```

### Routing logic (Python section of gateway)

```
load_agents(config_path):
  try:
    load TOML
    validate: catch-all (empty prefix) is last entry
  except any error:
    log error
    return [hardcoded_default_agent]   # R1: never die from bad config

route_message(text, agents):
  for agent in agents:
    if agent.prefix and text.startswith(agent.prefix):
      return agent, text[len(prefix):].strip()
  return default_agent, text

dispatch(agent, stripped_text):
  log(f"agent={agent.name} cwd={agent.cwd}")   # R5: always log dispatch
  if agent.system_prompt == "restricted":
    args = ["--system-prompt", TELEGRAM_SYSTEM_RESTRICTION]
    cwd  = "/tmp"
  else:
    args = []        # no override → CLAUDE.md loads from cwd
    cwd  = agent.cwd
  subprocess.run([claude_bin, "--dangerously-skip-permissions",
                  "--print", *args, "-p", stripped_text], cwd=cwd, ...)
```

### Pre-mortem requirements baked in

| Req | Implementation |
|---|---|
| R1 — bad TOML never kills gateway | `try/except` around `tomllib.load()`, hardcoded fallback |
| R2 — Python < 3.11 (dma64) | `try: import tomllib except ImportError: use hardcoded defaults, log warning` |
| R4 — catch-all must be last | Validated at load time; bad ordering → log + fallback |
| R5 — dispatch logged | `log(f"agent={name} cwd={cwd}")` on every message |

### User experience

```
/work what's in the _review folder   →  work agent (PROJ_ROOT, CLAUDE.md)
what time is it                       →  default agent (/tmp, restricted)
/work run healthcheck                 →  work agent (full project access)
```

### Security note

The `/work` agent runs `--dangerously-skip-permissions` with `cwd=PROJ_ROOT`. This is intentional — only the one authorized `TELEGRAM_CHAT_ID` can trigger it. The existing authorization gate in the gateway (numeric chat_id check before any message processing) is the security boundary. Log `ELEVATED:` prefix when work agent is dispatched so it's auditable.

---

## Delivery

- Feature 1: `scripts/refinery-doctor.sh` — one PR (`feat/refinery-doctor`)
- Feature 2: `config/telegram-agents.toml` + gateway changes — one PR (`feat/telegram-agent-routing`)
- Feature 3 (Docker sandbox): separate session, separate PR
- Both features wired into `install-reliability.sh` where applicable

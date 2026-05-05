# Handoff — Uncle J's Refinery

*Last updated: 2026-04-30*

Read this before touching anything. Work priorities are in order below.

---

## Current state

### Working

- 7 MCP servers registered: jcodemunch, jdatamunch, jdocmunch, mempalace, serena, duckdb, context7
- Global `CLAUDE.md` with routing policy, security rules, jOutputMunch rules
- Global skills: `prior-art-check`, `judge` (live in `global-skills/`)
- Guardrails: secret scanner (UserPromptSubmit) + injection defender + commit-time scan
- All Hermes features built and on disk:
  - `features/telegram-gateway/` — outbound Telegram notifications
  - `features/telegram-notify/` — notification backend
  - `features/auto-skill/` — Stop hook that auto-drafts skills from session transcripts
  - `features/ralph-cron/` — cron-safe Ralph loop wrapper with Telegram notifications
  - `features/skill-manager/` — skill install/link management
  - `features/stack-alerts/` — daily MCP version check with Telegram upgrade prompt
  - `features/mempalace/` — mempalace feature module
- `scripts/ralph-harness.sh` — bash port complete
- Git is in sync with `origin/main` (0 commits ahead)

### Blocked

**Langfuse — not running on Linux.** Three known failures in `install-langfuse.sh` on this machine (`dtfd-xfce`, Liquorix kernel 6.18.4-1-liquorix-amd64, Debian 13):

1. **ClickHouse 26.3.9.8 crashes at startup** — `stof: no conversion at getNumberOfCPUCoresToUseImpl()`. Liquorix kernel exposes empty `/sys` CPU topology. Fix: pin ClickHouse to `24.12` in `claude-code-langfuse-template/docker-compose.yml`.

2. **Python path issue** — the Stop hook venv python path is hardcoded. The install script patch block needs to resolve `$STACK_ROOT` at install time, not leave a literal path. Fix documented in previous HANDOFF (see mempalace `uncle_j_s_refinery/scripts` wing for full patch block).

3. **Third blocker** — check the previous HANDOFF in mempalace (`uncle_j_s_refinery/scripts/HANDOFF.md`) for the third specific failure. It was noted but not resolved.

### Uncommitted change

`.claude/settings.json` has one unstaged change: a mempalace convos mining hook added to the Stop hooks block:

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "/opt/proj/Uncle-J-s-Refinery/.venv/bin/mempalace mine /home/bill/.claude/projects --mode convos < /dev/null  # uncle-j-mempalace-convos",
      "async": true
    }
  ]
}
```

Commit this if it's intentional before starting Langfuse work.

---

## Priorities

### 1. Commit the settings.json change

```bash
cd /opt/proj/Uncle-J-s-Refinery
git add .claude/settings.json
git commit -m "feat: add mempalace convos mining Stop hook"
```

Then push (HTTPS remote — use a PAT or `gh auth login` if not already authenticated).

### 2. Fix Langfuse on Linux

Work through the three blockers above in order. The install script is at `install-langfuse.sh`. The docker-compose template is at `claude-code-langfuse-template/docker-compose.yml`.

After fixing, run:
```bash
./install-langfuse.sh
```

Verify Langfuse is reachable at `http://localhost:3050` before marking done.

### 3. Check stack-alerts configuration

`features/stack-alerts/` requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to be set. Verify these are in `.env` or system env and that the cron jobs are installed:

```bash
crontab -l | grep stack-alerts
```

---

## External tools audit (2026-04-30)

Reviewed jgravelle's full repo list. Nothing to add. The refinery already covers all MCP-relevant work he's published. `jmunch-mcp` (proxy) is redundant given the refinery tools do their own compression. `groqcrawl` has no MCP interface. `mcp-retrieval-spec` is for implementers, not consumers.

---

## Push access

Remote is HTTPS (`https://github.com/williamblair333/Uncle-J-s-Refinery.git`). No `gh` CLI installed on this machine. To push, either:
- Run `! gh auth login` in a Claude Code session (installs credential helper)
- Use a fine-scoped PAT as the password on first HTTPS push
- Add an SSH key and flip origin to the SSH URL

# Antigravity CLI (agy): headless use from scripts and other agents

Gemini CLI stopped serving personal Google accounts (AI Pro, Ultra, free) on 2026-06-18.
`agy` is the replacement and runs on the Google AI Pro subscription.

## Install

```bash
curl -fsSL -o /tmp/agy-install.sh https://antigravity.google/cli/install.sh   # read it, then:
bash /tmp/agy-install.sh && agy          # sign in with the Google AI Pro account
bash features/antigravity/install.sh     # permissions, MCP servers, rules, skills
```

## Pieces

| File | What it does |
|---|---|
| `install.sh` | Runs the four steps below; every step merges and keeps a `.bak`. |
| `permissions.json` | Read-only shell allow list, MCP allow list (read-oriented servers, Serena read tools only, no DuckDB), deny list for destructive commands and index-deleting tools. |
| `apply_permissions.py` | Merges those rules into `~/.gemini/antigravity-cli/settings.json` (keeps agy's own keys). |
| `sync_mcp.py` | Copies Claude's user-scope MCP servers (`~/.claude.json`) into `~/.gemini/config/mcp_config.json` (mode 0600; agy-only servers kept). Re-run when registrations change. |
| `install_rules.py` + `rules-block.md` | Marker-delimited block in `~/.gemini/GEMINI.md` that includes `CLAUDE.md` via `@[...](path)` plus the Claude→agy translations. The rest of the file is left alone. |
| `../../scripts/ask_agy.py` | Runs one prompt headless; exit 0 only when the turn really succeeded. |
| `../../scripts/referee.py` | Gemini judges a diff, files or text against a task; JSON verdict, exit 0 pass / 2 fail / 3 unsure / 1 error. See the `referee` skill. |

```bash
.venv/bin/python scripts/ask_agy.py --cwd /path/to/repo "question"
.venv/bin/python scripts/ask_agy.py --cwd /tmp/work --edits "/to-questionnaire ..."
```

Verified live 2026-10-15: jcodemunch `resolve_repo` and memweave `memory_search` called from
agy; the routing policy's heading and table quoted back from the rules context, both in this
repo and in an untrusted project (`/opt/proj/voice-line`).

## Why the wrapper exists

In print mode agy exits 0 with `status: SUCCESS` even when the work did not happen:

- **Deny rule hit:** the tool step ends in `ERROR`, `denied_actions` stays empty, and the
  model often answers "DONE" anyway.
- **Command on no list:** it is soft-denied (`denied_actions` set) and the response is empty.

`ask_agy.py` reads the stream-json events and fails on either, naming the command.

A soft deny also ends the turn, so a prompt that invites "check it yourself" gets an empty
answer the moment the model reaches for `python` or `pytest`. `referee.py` names the
allowed commands in its prompt, read from `permissions.json`.

## Models

`agy models` lists Gemini 3.8 Flash (low/medium/high), Claude Opus and Sonnet 5.5, and
GPT-OSS 120B, and the stream doesn't say which one ran. Pass `--model` whenever the
provider matters. `referee.py` pins `gemini-3.8-flash-medium` and refuses `claude-*`. On a
10 KB file review the default model was still thinking at the 4-minute timeout (~32k thinking
tokens); Flash medium answered in about 3.5 minutes.

## Verified behaviour (agy 1.3.5, 2026-10-15)

Re-run these after an agy update: it self-updates and rule matching is closed source.

| Probe | Result |
|---|---|
| `ls -la` (allowed) | runs |
| `ls; touch X` (touch denied) | blocked: "Matches user-configured deny rule" |
| `ls && mkdir X` (mkdir on no list) | soft-denied, nothing created |
| `ls $(touch X)`, `echo x \| xargs touch X` | denied |
| `cat /etc/hostname > ~/file` (write outside workspace) | denied, nothing written |

Each part of a compound command is checked separately, so allowing `ls` does not allow
what is chained after it.

## Skills

agy reads `~/.gemini/skills` (linked by `scripts/skill-link.sh`). `/skills` lists all of
ours, but in print mode only agy's built-ins sit in the model's context, so our skills do
not fire on their own: invoke them by name (`/teach`, `/to-questionnaire ...`).

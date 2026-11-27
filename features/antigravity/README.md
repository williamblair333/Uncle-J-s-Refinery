# Antigravity CLI (agy): headless use from scripts and other agents

Use `agy` to run Gemini from a script or another assistant without opening an interactive session. It runs on a Google AI Pro subscription. Gemini CLI stopped serving personal Google accounts (AI Pro, Ultra, and free) on 2026-06-18. `agy` replaces it.

## Install

```bash
curl -fsSL -o /tmp/agy-install.sh https://antigravity.google/cli/install.sh   # read it, then:
bash /tmp/agy-install.sh && agy          # sign in with the Google AI Pro account
bash features/antigravity/install.sh     # permissions, MCP servers, rules, skills
just agy-login                           # one more sign-in, for jobs: see "The jail" below
```

## Pieces

| File | What it does |
|---|---|
| `install.sh` | Runs the five steps below. Each step merges changes and saves a `.bak` backup. |
| `agy-jail` | The empty root every `ask_agy` job starts in. See "The jail" below. |
| `sandbox-run` | The only way agy runs code. It uses bubblewrap, a tool that limits what a process can see and use. It cuts off network access and gives the process an empty home with only uv mounted inside. Only the current directory is writable. agy's own `--sandbox` keeps network access and the user account (probed 2026-10-26). Find the wrapper in `~/.local/bin`. |
| `permissions.json` | Lists which shell commands and MCP tools agy may use. MCP servers give an assistant access to tools. The list allows read-only shell commands and servers built for reading, including only Serena's read tools. It excludes DuckDB and blocks destructive commands and tools that delete indexes. |
| `apply_permissions.py` | Merges those rules into `~/.gemini/antigravity-cli/settings.json` (keeps agy's own keys). |
| `sync_mcp.py` | Copies Claude's user-scope MCP servers (`~/.claude.json`) into `~/.gemini/config/mcp_config.json` (mode 0600; agy-only servers kept). Always adds the agy-only `fetch` server (pinned `mcp-server-fetch`): agy's own `read_url` is not registered in headless mode. Re-run when registrations change. |
| `install_rules.py` + `rules-block.md` | Marker-delimited block in `~/.gemini/GEMINI.md` that includes `CLAUDE.md` via `@[...](path)` plus the Claude→agy translations. The rest of the file is left alone. |
| `../../scripts/ask_agy.py` | Runs one prompt headless; exit 0 only when the turn really succeeded. |
| `../../scripts/referee.py` | Gemini judges a diff, files or text against a task; JSON verdict, exit 0 pass / 2 fail / 3 unsure / 1 error. See the `referee` skill. |

```bash
.venv/bin/python scripts/ask_agy.py --cwd /path/to/repo "question"
.venv/bin/python scripts/ask_agy.py --cwd /tmp/work --edits "/to-questionnaire ..."
```

Verified live 2026-10-15: jcodemunch `resolve_repo` called from agy; the routing policy's
heading and table quoted back from the rules context, both in this repo and in an untrusted
project (`/opt/proj/voice-line`). agy lost memweave on 2026-11-07, because its store holds
transcripts from local-only projects. Put what agy needs from past sessions in the brief.

## The jail

`ask_agy` starts every job through `agy-jail`, which uses bubblewrap to start the job with an empty view of the filesystem.
Deny rules alone don't keep files private. In a test on 2026-11-07, a rule stopped `read_file` from opening a test file, but `cat` still printed it. The rule applied only to `read_file`. The jail hides files from every tool, not just the ones a rule names. A job sees only its repo (writable), agy's own state, the tools and MCP servers' code
(read-only) and `config/agy-jail-extra.txt`. It refuses to start in a `config/delegate-local-only.txt`
path, or in your home, and masks those paths and secret-named files inside the repo. Its MCP servers
are agy's children, so they're inside too. Indexes and package caches live in
`~/.local/state/agy-jail`, so nothing a job writes there runs outside.

- **Login:** agy's normal login is in the desktop keyring, over the session bus, which would let a job
  run commands outside (`systemctl --user`). Jobs use a token file instead: run `just agy-login` once
  per host. It lands in `~/.gemini/antigravity-cli/antigravity-oauth-token` (mode 0600).
- **Other repos:** a job can't read a neighbouring repo. Add a read-only path to
  `config/agy-jail-extra.txt`, or `AGY_JAIL_EXTRA` for one host. A path overlapping a local-only one is skipped.
- **Git:** `.git/hooks` and `.git/config` are read-only, since git runs what they name outside, on your
  next command. Tracked secret-named files stay visible: history already shows them, and masking one
  would let `git add` stage it as empty.
- **Not covered:** the network is shared, so localhost services are reachable (Gitea without
  credentials, Ollama). Gitignored files in the job's repo are visible unless they match the masks.
  Running `agy` by hand stays outside the jail. Files a job edits in its repo (scripts, a Makefile, a
  folder already set as `core.hooksPath`) run when you run them, so review its changes as usual.

Verified 2026-11-07 with real agy jobs: `cat`, `read_file`, jcodemunch `index_folder` and serena
`activate_project` on hidden paths all returned nothing, while `fetch`, context7 and the job folder worked.

## Why the wrapper exists

In print mode, which runs a prompt without the interactive interface, agy exits 0 with `status: SUCCESS` even when the work did not happen:

- **Deny rule hit:** the tool step ends in `ERROR`, `denied_actions` stays empty, and the
  model often answers "DONE" anyway.
- **Command on neither list.** agy sets `denied_actions` and returns an empty response. This is a soft deny.

`ask_agy.py` reads the events agy emits as it works. If it detects either kind of denial, it fails and names the command.

A soft deny also ends the turn. So if a prompt says "check it yourself" and the model runs `python` or `pytest`, which aren't allowed, the answer comes back empty. `referee.py` reads the allowed commands from `permissions.json` and names them in its prompt.

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

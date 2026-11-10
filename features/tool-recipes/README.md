# tool-recipes

Hard, useful jobs become one-command tools that any session, on any host, can find and run instead of working them out again. The rules a tool meets are in [docs/TOOLS-STANDARD.md](../../docs/TOOLS-STANDARD.md).

| Piece | What it does |
|---|---|
| `scripts/tools.py` | `list` searches every project's recipes, `lint` checks a repo's tools against the standard, `sync` writes the global justfile. |
| `scripts/inbox.py` | Notes between projects: `send`, `list`, `done`, and the session-start `notice`. |
| `scripts/tool_miner.py` | Reads recent transcripts and lists jobs done by hand in 3+ sessions, as candidates for tools. |
| `hooks/session-start.sh` | Shows unread inbox notes. Re-syncs the global justfile in the background when a project's justfile is newer. Always exits 0. |
| `template.sh` | Starting point for a new tool. Passes every lint rule except the test. |
| `install.sh` | Registers the hook in `~/.claude/settings.json` (marker-keyed, backup, atomic) and runs the first sync. `--check`, `--dry-run`, `--uninstall`. |

## Everyday use

```bash
just -g tools backup                  # find a recipe in any project
just -g hearth status                 # run Hearth's status from anywhere
just tools lint /opt/proj/autark      # how Autark's tools measure up (--all for the backlog)
just inbox send hearth --topic "need a status --json"   # ask Hearth to change something
just tool-mine                        # what keeps being done by hand
```

## Setup on another host

`just` must be installed (1.40 is tested). Then run `bash features/tool-recipes/install.sh`. If the projects aren't in `/opt/proj`, set `PROJ_ROOT` in the environment Claude Code starts with.

## Removing it

`bash features/tool-recipes/install.sh --uninstall` removes the hook. Delete `~/.config/just/justfile` by hand if you no longer want `just -g`. Inbox folders ignore themselves in git, so they never show up in a commit.

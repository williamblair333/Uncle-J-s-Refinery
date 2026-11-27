# tool-recipes

Hard, useful jobs become one-command tools. Any session, on any host, can find and run them instead of working them out again. The rules every tool must meet are in [docs/TOOLS-STANDARD.md](../../docs/TOOLS-STANDARD.md).

| Piece | What it does |
|---|---|
| `scripts/tools.py` | `list` searches every project's recipes. `lint` checks a repo's tools against the standard. `sync` writes the global justfile, the shared list of recipes that the command runner loads. |
| `scripts/inbox.py` | Notes between projects: `send`, `list`, `done`, and the session-start `notice`. |
| `scripts/tool_miner.py` | Reads recent session transcripts and lists jobs done by hand in 3+ sessions as candidates to turn into tools. |
| `hooks/session-start.sh` | Shows unread inbox notes. Re-syncs the global justfile in the background when a project's justfile is newer. Always exits 0. |
| `template.sh` | Start here when writing a tool. The template meets every lint rule apart from the test requirement. |
| `install.sh` | Registers the hook in `~/.claude/settings.json` and runs the first sync. The hook entry carries a marker, so a rerun replaces it instead of adding a second copy. It saves a backup first and writes the new file in one step, so a crash can't leave it half-written. `--check`, `--dry-run`, `--uninstall`. |

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

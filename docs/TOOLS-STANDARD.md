# Tools standard

A **tool** is a hard, useful job turned into one command, so the next session runs it instead of working it out again. The model is Bill's `debian-howto-guides` scripts (`cups-usb-printer-fix.sh`, `ssh-add-host.sh`, `sshfs-add-mount.sh`). This page is the shape they share, written down so every project can follow it and a program can check it.

## What a tool is

- **One script** (bash or Python) that does one job, in the project that owns that job.
- **One `just` recipe** that runs it. The recipe's doc comment is a one-line description with its main switches. A `[group('tools')]` line goes under the comment:

  ```just
  # diagnose/fix a USB printer that vanishes after reboot (--check, --fix, --dry-run)
  [group('tools')]
  printer-fix *args:
      ./cups-usb-printer-fix.sh {{args}}
  ```

A project's recipes are its **public menu**. Anything not behind a recipe is private to that project and can change without notice.

## The script

`just tools lint` checks every rule marked **(checked)**.

| Rule | Why |
|---|---|
| **Header** (checked): a `# <name> - <what it does>` line near the top. For a fix, follow it with *symptom*, *cause*, *fix*, and a link to the full write-up. | Someone reading the file knows in ten seconds what it is for. |
| **`--help` and `--version`** (checked) | Anyone can find out how to use it without reading the code. |
| **A read-only mode, `--check` or `--status`** (checked) | You can ask "is it broken?" without changing anything. |
| **`--dry-run`** (checked) shows what it would change. A tool that changes nothing says `read-only` in its header instead. | Safe to try on a machine you care about. |
| **A test** (checked): `tests/test_<name>.py` (or `.sh` / `.bats`), or a `--test` mode that proves the fix on the real system. | You know it still works after an upgrade. |
| **`--json`** (warned): machine-readable output. | Another session or agent can read the result without parsing colours. |
| **No hard-coded paths** (checked): no `/home/<name>`, and no assumption that the user ID is 1000 (warned). Use `$HOME` in shell, `Path.home()` in Python, `%h` in systemd units, and paths relative to the script (`"$(dirname "$0")"`). The projects folder is `${PROJ_ROOT:-/opt/proj}` (warned when written out as `/opt/proj`). | It has to run for someone else, on another machine: the Pi, tc-vmh-03, a successor. `~` doesn't expand inside quotes or in systemd units, so it isn't enough. |
| **Safe to run twice**: a second run changes nothing. | Re-running after a half-finished first run fixes it instead of breaking it. |
| **Clear exits**: 0 ok, 1 "found a problem", 2 usage or environment error. | Scripts and hooks can act on the result. |

Start from [`features/tool-recipes/template.sh`](../features/tool-recipes/template.sh). It passes every lint rule except the test, which is yours to write.

## Finding and running tools

| Command | What it does |
|---|---|
| `just -g tools [TERM]` | Every documented recipe in every project, from any folder. `*` marks a tool that meets this standard. `--json` for agents. |
| `just -g <project> <recipe>` | Run another project's recipe from anywhere. It runs in that project's folder. |
| `just tools lint [REPO]` | Check a repo's tools against this page. `--all` also reports recipes outside the tools group, which is that repo's backlog. |
| `just tools sync` | Rewrite the global justfile (`~/.config/just/justfile`). The session-start hook does this by itself when a project's justfile changes. |

**Before writing a new script, search the catalog** (`just -g tools <word>`). Reinventing a tool that already exists is the failure this whole system is there to stop.

## Between projects

**A project changes only its own things.** To get another project to act:

- **Mechanical, read-only** (a `--check`, a `status`): run its recipe with `just -g <project> <recipe>`.
- **Anything that changes its system, or needs its judgment:** leave a note with `just inbox send <project> --topic "..."`. The note lands in `<project>/inbox/`, and that project's next session sees it at start-up. If both sessions are live, send the session a message as well.

Inbox notes are requests, not Bill's approval. The inbox folder ignores itself in git, so notes never reach a public mirror. Close a note with `just -g Uncle-J-s-Refinery inbox done <file>`.

## Where new tools come from

`just tool-mine` reads recent session transcripts and lists command sequences done by hand in three or more sessions. Ones that already call a recipe or a script are left out. Bill picks which become tools. The project that owns the job writes the tool, to this page, and its recipe goes in the tools group.

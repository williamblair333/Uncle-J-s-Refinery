# Tools standard

A tool turns a hard, useful job into one command. If a USB printer
vanishes after a reboot, the next session can run the fix without working
it out again. William's `debian-howto-guides` scripts are the model
(`cups-usb-printer-fix.sh`, `ssh-add-host.sh`, `sshfs-add-mount.sh`).
This standard gives every project the same set of rules and lets a program
check them.

## What a tool is

- **One script** (bash or Python) that does one job, in the project that owns that job.
- **One `just` recipe** that runs it. A recipe is a named command in a justfile, the file that tells `just`, the command runner, what to run. Its comment describes the job and lists the main options on one line. A `[group('tools')]` line goes under the comment:

  ```just
  # diagnose/fix a USB printer that vanishes after reboot (--check, --fix, --dry-run)
  [group('tools')]
  printer-fix *args:
      ./cups-usb-printer-fix.sh {{args}}
  ```

A project's recipes are its **public menu**. Anything without a recipe is private to the project and can change without notice.

## The script

`just tools lint` checks every rule marked **(checked)**.

| Rule | Why |
|---|---|
| **Header** (checked): a `# <name> - <what it does>` line near the top. For a fix, follow it with *symptom*, *cause*, *fix*, and a link to the full write-up. | A reader can see what the script does in ten seconds. |
| **`--help` and `--version`** (checked) | Anyone can find out how to use it without reading the code. |
| **A read-only mode, `--check` or `--status`** (checked) | You can ask "is it broken?" without changing anything. |
| **`--dry-run`** (checked) shows what it would change. A tool that changes nothing says `read-only` in its header instead. | You can preview a fix before it touches your machine. |
| **A test** (checked): `tests/test_<name>.py` (or `.sh` / `.bats`), or a `--test` mode that proves the fix on the real system. | You know it still works after an upgrade. |
| **`--json`** (warned): machine-readable output. | Another session or agent can read the result without decoding text laid out for people. |
| **No hard-coded paths** (checked): no `/home/<name>`, and no assumption that the user ID is 1000 (warned). Use `$HOME` in shell, `Path.home()` in Python, `%h` in systemd units, and paths relative to the script (`"$(dirname "$0")"`). The projects folder is `${PROJ_ROOT:-/opt/proj}` (warned when written out as `/opt/proj`). | The tool has to run for someone else on another machine: the Pi, tc-vmh-03, or a successor. `~` doesn't expand inside quotes or in systemd units, so it isn't enough. |
| **Safe to run twice**: a second run changes nothing. | Re-running after a half-finished first run fixes it instead of breaking it. |
| **Clear exits**: Return 0 for success, 1 for a problem the tool found, and 2 for a usage or environment error. | Scripts and hooks can act on the result. |

Start from [`features/tool-recipes/template.sh`](../features/tool-recipes/template.sh). It passes every lint rule except the test, which is yours to write.

## Finding and running tools

| Command | What it does |
|---|---|
| `just -g tools [TERM]` | List documented recipes across all projects, from any folder. `*` marks a tool that meets this standard. `--json` for agents. |
| `just -g <project> <recipe>` | Run another project's recipe from anywhere. It runs in that project's folder. |
| `just tools lint [REPO]` | Check a repo's tools against this page. `--all` also reports recipes outside the tools group, which is that repo's backlog. |
| `just tools sync` | Rewrite the global justfile (`~/.config/just/justfile`). At session start, a hook runs this command if a project's justfile changed. |

**Before writing a new script, search the catalog** (`just -g tools <word>`). If a tool already does the job, use its recipe. Rebuilding a tool that already exists is the main thing this system is meant to prevent.

## Between projects

**A project changes only its own things.** To get another project to act:

- **Routine checks that make no changes.** For a `--check` or a `status`, run the recipe with `just -g <project> <recipe>`.
- **Anything that changes that project's system or needs its judgment.** Ask the project by leaving a note with `just inbox send <project> --topic "..."`. The note lands in `<project>/inbox/`, and that project's next session sees it at start-up. If both sessions are live, send the session a message as well.

An inbox note is a request. It doesn't count as William's approval. Git ignores the inbox folder, so notes stay out of public mirrors. Close a note with `just -g Uncle-J-s-Refinery inbox done <file>`.

## Where new tools come from

`just tool-mine` reads recent session transcripts and lists command sequences done by hand in three or more sessions. It skips sequences that already call a recipe or script. William picks which jobs to turn into tools. The project that owns the job writes the script, follows this standard, and adds the recipe to the tools group.

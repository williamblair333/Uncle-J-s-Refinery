# Windows Port

This guide explains how the stack runs on Windows 11 with Git Bash, a shell
that lets Windows run Bash scripts. It covers the changes the port needed and what still runs only on Linux. See `PORTING.md` for the move from Claude Code to
Hermes.

Ported and verified 2026-07-30 against Windows 11 IoT Enterprise LTSC 2024
(10.0.26100), Git Bash 5.3.15 (MINGW64), Python 3.11.15, uv 0.12.0.

## Host prerequisites

| Component | Location | Notes |
|---|---|---|
| uv 0.12.0 | `C:\util\apps\uv` | On user PATH. SHA256-verified download. |
| Python 3.11.15 | uv-managed | `uv python install 3.11`. Statically links SQLite **3.53.1**. |
| Git Bash 5.3.15 | `C:\util\apps\Git\bin\bash.exe` | Not on the Windows PATH — hooks must name it absolutely. |
| `python3` shim | `C:\Users\william\.local\bin\python3` | Extensionless bash wrapper. Several scripts call `python3`, which does not exist as a command name on Windows. |
| jq 1.7.1 | `C:\util\apps\jq` | On user PATH. sha256 `7451FBBF37FEFFB9BF262BD97C54F0DA558C63F0748E64152DD87B0A07B6D6AB`. |

**jq is required.** It reads and writes JSON. Three Claude Code hooks
(commands that run at points such as session start) use `jq` to read their
input and return a decision. They are `hooks/discipline/grep-guard.sh`,
`edit-surface-guard.sh` and `unpushed-warn.sh`. The installer,
`install-reliability.sh`, also uses `jq` to register them in `settings.json`.
An earlier revision missed these uses after one hook switched to the venv's
Python. A venv is a project's own Python environment. Without jq, none of this shows an error. See "Guards that fail open" below.

Hooks may start without the user's PATH, the list of folders Windows searches
for commands. Both `scripts/win/hook.sh` and `scripts/win/run-job.sh` put
`.venv/Scripts`, `C:\util\apps\jq` and `C:\util\apps\uv` at the front of that list.

## SQLite: the vendored pysqlite3 pin is moot here

The SQLite build from Python on Windows already includes the fix this
project needs. The bug was a data race in WAL, SQLite's write-ahead log. SQLite
records writes in that log before applying them to the main database.
The bug affects 3.7.0–3.51.2.

`pyproject.toml` pins a vendored pysqlite3 wheel, a Python package build
supplied with the project, that uses SQLite 3.51.3. Its platform rule limits it
to `linux/x86_64`. On Windows, `uv sync` falls back to the PyPI build of
pysqlite3 (3.51.1). That build stays inactive because the setup never creates
`_pysqlite3_patch.pth`. The venv uses Python's built-in `sqlite3` module.
The uv build of CPython 3.11.15 links it to SQLite **3.53.1**.

`healthcheck.sh` used to require `sqlite_version == 3.51.3`, so it rejected
the newer Windows build. Keep the check at `>= 3.51.3` so it accepts versions
that include the WAL fix.

## Hook wiring

Windows hooks route through one dispatcher, `scripts/win/hook.sh <action>`:

```
C:/util/apps/Git/bin/bash.exe C:/opt/proj/Uncle-J-s-Refinery/scripts/win/hook.sh <action>
```

**Keep Windows hooks in `.claude/settings.local.json`.** Git ignores this file,
so its settings stay on the machine that uses them. The committed
`.claude/settings.json` is shared with Linux. Putting
`C:/util/apps/Git/bin/bash.exe` there made every hook fail at SessionStart/Stop
on Linux with "No such file or directory." Keep the Linux commands
(`bash /opt/proj/.../scripts/*.sh`) in the committed `.claude/settings.json`.

Copy the ready-made `scripts/win/settings.local.json` on first setup and after
any pull that changes it:

```
cp scripts/win/settings.local.json .claude/settings.local.json
```

Claude Code runs hooks from both `settings.local.json` and `settings.json`. A local file can't turn off a committed hook.
Each committed Linux command starts with
`[ -d /opt/proj/Uncle-J-s-Refinery ] || exit 0;`. On Windows that directory
is absent, so each Linux hook exits 0 before doing anything. That avoids "not found" noise next to the real Windows hooks.

Keep `MSYS=winsymlinks:nativestrict` in the local file as well, never in the committed one. MSYS is the
layer that lets Git Bash use Unix-style commands and paths on Windows.

The dispatcher gives Windows the full path to `bash`, which is absent
from PATH. It also lets Bash handle redirection such as `>> log 2>&1` and
`2>/dev/null || true`. When settings.json launches a script directly,
there is no shell to handle that syntax and the redirection gets dropped.

In `.claude/settings.local.json`, `MSYS=winsymlinks:nativestrict` lets
`skill-link.sh` create native symlinks, or filesystem pointers to other paths.
Without the setting, the script copies whole directories. Native symlinks
require Windows Developer Mode or a shell running as administrator.

### Hook shell — confirmed

Claude Code runs hooks under Git Bash on win32, the Windows platform. On SessionStart,
`scripts/win/shell-probe.sh` appends the shell details to
`state/win-port-probe.log`. It recorded `bash 5.3.15(1)-release` on
`MINGW64_NT-10.0-26100`, confirming the command format. You can delete the
probe.

The probe also reported `uv`, `uvx` and `jq` as MISSING, even though
`C:\util\apps\uv` was on the user PATH. That is why `hook.sh` and
`run-job.sh` add the directories themselves.

## The POSIX venv shim

Linux and Windows put a venv's commands in different folders. About 20 places
in `install.sh`, `healthcheck.sh` and `scripts/` look for
`$ROOT/.venv/bin/<tool>`, the POSIX (Unix-style) layout. A shim is a small
compatibility layer. Here, `scripts/win/venv-compat.sh` supplies the paths
those callers expect:

- `.venv/bin` points to `.venv/Scripts`. MSYS adds `.exe` when it launches a
  command, so `.venv/bin/jcodemunch-mcp` finds `jcodemunch-mcp.exe`.
- `.venv/Scripts/python3.exe` is a copy of `python.exe`. It supplies the
  `python3` name that POSIX venvs provide.

Git ignores `.venv/`, and a rebuild removes both shims (`uv sync`, `uv venv`).
`hook.sh autofix` restores them on every SessionStart. If you rebuild outside
a session, run `bash scripts/win/venv-compat.sh` yourself.

An MCP server is a program that gives an AI assistant access to tools or
data. Claude Code starts these servers with `CreateProcess`, a Windows
function for launching programs. Use explicit `.venv\Scripts\*.exe` paths.
This launch cannot rely on the `bin` symlink or on Bash
adding `.exe`.

## MCP server registration

Copy the Windows server list from `scripts/win/mcp.json` to the repo root
as `.mcp.json`. Git ignores the root copy so the commands stay local to this host.

    cp scripts/win/mcp.json .mcp.json

Claude Code gives a project's `.mcp.json` priority over user settings for
servers with the same names. When the root file contained Windows-only
`C:\...` commands, Linux sessions quietly lost all five stack servers.
This is the same shared-file trap as the hook block above (see PR #103, which restored the hook settings). Keeping the filename means the existing
`enabledMcpjsonServers` approval in `~/.claude.json` still applies.

The project's `.mcp.json` registers three servers. Their commands take different arguments, and this is the easiest thing to get wrong. Here, stdio means the server talks to Claude Code through the
process's standard input and output.

| Server | Invocation |
|---|---|
| jcodemunch | `serve --transport stdio` |
| jdatamunch | *no arguments at all* — a bare invocation is the stdio server |
| jdocmunch | `serve` — has the subcommand but **no** `--transport` flag |

Passing `--transport stdio` to the latter two makes them exit immediately, which
surfaces as `MCP error -32000: Connection closed`.

Do **not** use `jcodemunch-mcp init` / `install claude-code` on this host: it
registers via floating `uvx`, appends a policy block to *global*
`~/.claude/CLAUDE.md`, and writes hooks into *global* `~/.claude/settings.json` —
all contrary to the project-scoped setup here. It also resolves "project" against
the current working directory, not this repo.

## `flock` — the silent-failure class

The `flock` command lets a script claim a lock so two copies don't run at
once. MSYS lacks it. Every `flock -n` check failed, and the scripts treated
that failure as "already running." Callers saw success even though the jobs skipped their work. This wasn't cosmetic: it quietly turned off real work.

- `scripts/jcodemunch-reindex.sh` — skipped the reindex, logged `reindex: OK`
- `scripts/jdocmunch-reindex.sh` — same
- `scripts/telegram-gateway-poll.sh` — exited every run, so the gateway never polled
- `scripts/memweave/sync_memory.sh` — skipped every sync
- `scripts/session-start-autofix.sh` — skipped the async stack upgrade

The scripts now claim the lock by creating a directory with `mkdir`. Only one
process can create that directory first. An `EXIT` trap tells the shell to
remove the lock when the script exits. This works the same way on Linux
and needs no external binary.

## Path-comparison correctness

The old checkpoint hook compared the text from `git rev-parse --show-toplevel`
with the literal `/opt/proj/Uncle-J-s-Refinery`. On Windows, Git reports
`C:/opt/proj/...`, so the check never matched. Comparing text was fragile on
Linux too.

Rewriting path strings into one form isn't enough. Under MSYS, `C:/x` and `/c/x` can name the same directory. An alias can even
map `C:/Users/<u>/AppData/Local/Temp` to `/tmp`. The new hook,
`scripts/win/checkpoint.sh`, uses `[ a -ef b ]` to compare the filesystem's
device and inode identifiers. That tells it whether the paths lead to the
same directory on either platform.

Two scripts also hardcoded the repo root and now derive it from
`${BASH_SOURCE[0]}`: `session-start-autofix.sh`, `memweave/sync_memory.sh`.

`sync_memory.sh` additionally derived the Claude transcript directory name as the
Linux form `-opt-proj-Uncle-J-s-Refinery`. Claude maps `:` `/` `\` → `-`, so on
Windows it is `C--opt-proj-Uncle-J-s-Refinery`; the slug is now computed.

## Also enabled during the port

| Thing | Where |
|---|---|
| ONNX embedding model (86 MB, all-MiniLM-L6-v2) | `~/.code-index/models/` — `jcodemunch-mcp download-model` |
| `JCODEMUNCH_EMBED_MODEL=all-MiniLM-L6-v2` | `.env` (gitignored) — required for semantic search |
| Embedding canary (16 strings, 384d) | `~/.code-index/embed_canary.json` — `scripts/pin-canary.sh` |
| jdocmunch doc index | `jdocmunch-mcp index-local --path <repo>`. Note `jdocmunch-reindex.sh` only *refreshes* an existing index; it cannot create the first one. |
| `.venv-memweave` (Python 3.12 + memweave) | `uv venv` + `uv pip install memweave onnxruntime tokenizers numpy` |
| git post-merge hook | symlink `.git/hooks/post-merge` → `scripts/post-merge-hook.sh` |
| 6 agents, 44 skills | symlinked into `~/.claude/agents` and `~/.claude/skills` |
| `MCP_TIMEOUT=60000` | *global* `~/.claude/settings.json` (what `install.sh` step 5b does) |
| MCP pre-approval | `~/.claude.json` → `projects[<repo>].enabledMcpjsonServers`, avoiding a first-run trust prompt |

Both global files were backed up to `*.bak.winport` before editing.

Note skills and agents are inherently global — `~/.claude/skills` has no
project-scoped equivalent — and `skill-link.sh:38` treats `global-skills` as
link-only/never-unlink, so they stay visible in every project. `healthcheck.sh`
records their absence as a failure, so removing them is not a stable state.

## Still Linux-only (deliberately not ported)

| Area | Blocker / decision |
|---|---|
| serena / context7 / MotherDuck MCP | serena and MotherDuck would work via the now-installed `uvx`; context7 needs Node.js/`npx`, absent. Left out — supplementary to the jMunch trio, and unverified on Windows. |
| `features/` installers | `/stats`, `/dream` and the `dream-synthesizer` skill are uninstalled. Listed in `state/disabled-features` so the healthcheck reports them as `--`, not as failures. |
| `build-vendored-pysqlite3.sh` | Builds a Linux wheel; unnecessary here (see SQLite above). |
| Telegram gateway | Runs, but needs `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` and was never exercised. |

The 7 cron jobs now run on Windows too. See "Scheduled jobs" below.

`healthcheck.sh --quick` went from 21 failures to 8 and then to **ok**.
The last 8 came from checks that expected a Linux setup. On Windows,
`healthcheck.sh` now checks `schtasks` for scheduled jobs in place of
`crontab`. It shows `--` for unregistered supplementary MCP servers instead of a failure
and honors the list in `state/disabled-features`.

## Guards that fail open

A guard *fails open* when an error lets the action go ahead. These hooks rely
on `jq` to read the request and return a decision. Without jq, the failures
looked like this:

- In `grep-guard.sh:19`, `jq … 2>/dev/null || true` left `CMD` empty. The
  guard had nothing to match and exited 0. Claude Code allowed the command
  because it received no decision.
- `edit-surface-guard.sh` was supposed to fail closed, which means blocking
  the edit on error. It used `jq -n` to print every denial. Without jq it printed nothing and the edit went through. A guard meant to fail closed failed open instead, which is worse than having no guard.
- `install-reliability.sh:107-138` used jq to register the guards. It warned
  and kept going on failure, leaving the guards out of `settings.json`.

All three now exit non-zero when jq is missing. Two further Windows-specific
defects had the same silent character:

- `grep-guard.sh` hardcoded `REPO_ROOT=/opt/proj`; here the repo is
  `/c/opt/proj`. A wrong root does not error — it makes every absolute path look
  external to the repo, which is the guard's own allow condition. Both spellings
  are now treated as in-repo.
- `edit-surface-guard.sh` validated its clearance token by handing an MSYS path
  (`/tmp/premortem-cleared-…`) to a **native** `python3`, which cannot open it.
  Every edit was denied with no way to clear. Converted with `cygpath -m`
  (forward slashes; `-w` emits backslashes and breaks the Python literal).

`hooks/pre-mortem-guard/write-clearance-token.sh` **was in no repo at all** — it
lived only on the original Linux host while two consumers referenced it by path.
Wiring the guard on a fresh machine therefore installs a lock with no key. It is
now version-controlled. Check it first when porting to another machine.

## Scheduled jobs

`scripts/win/schedule-tasks.sh` registers four Task Scheduler jobs; task names
match the cron labels so `healthcheck.sh` probes either scheduler through one
accessor. `--remove` unregisters them.

| Job | Time |
|---|---|
| `uncle-j-jcodemunch-reindex` | 01:00 |
| `uncle-j-jdocmunch-reindex` | 01:30 |
| `uncle-j-memweave-sync` | 02:30 |
| `uncle-j-auto-maintain` | 03:00 |

`schedule-tasks.ps1` enables `StartWhenAvailable` so a missed job can run
after the machine wakes. The default is false, and `schtasks.exe` has no flag
to turn it on. Jobs registered with `schtasks.exe` skip any start time that passes while the machine is asleep. They don't run later, so its four tasks would never fire on a workstation. Two more traps:

- Git Bash's MSYS layer rewrites arguments that look like Unix paths. In
  `schtasks /query`, it turns the option into `C:/util/apps/Git/query`.
  Use `MSYS2_ARG_CONV_EXCL='*'` to turn off that rewriting.
- Under `set -o pipefail`, `printf "$big" | grep -q X` can report a failed
  search even when it finds a match. `grep -q` stops at the first hit. If
  output is still flowing, `printf` gets SIGPIPE, the signal for writing
  to a closed pipe. This worked with `crontab -l`, but the roughly 75KB of
  output from schtasks made every registered job look missing. Use
  `[[ "$haystack" == *"$needle"* ]]` to check for the text without a pipe.

`auto-maintain` runs `uv sync --inexact`, which destroys the `.venv/bin` shims the
other three jobs resolve through. `run-job.sh` re-asserts `venv-compat.sh` before
every job and again after auto-maintain; otherwise the 01:00 reindex breaks the
following night with no session open to self-heal.

Reindex lock dirs are reclaimed after 2h — the `EXIT` trap cannot fire on kill,
and a machine sleeping mid-reindex leaves a dir that skips every later run while
logging "already running".

`scripts/lib/tg_security.py` **was** Linux-only (`import fcntl` at module scope,
which broke `pytest` collection for the entire suite). It now selects
`fcntl`/`msvcrt` at import time and locks best-effort. Note `msvcrt.locking`
gives up after ~10s where `flock` waits indefinitely.

## Test baseline on Windows

On Windows, `pytest` reported 585 passed and 106 failed. All 106 failures
also occurred when the same subset ran in a clean worktree at `HEAD`.
The counts matched. The failures were checks of skill metadata in
`test_skills.py` (45) and checks in `test_session_end_check.py` and related
files (61). The Windows changes introduced no regression.

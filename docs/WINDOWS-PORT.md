# Windows Port

How this stack runs on Windows 11 + Git Bash, what had to change, and what is
still Linux-only. Companion to `PORTING.md` (which covers porting *away* from
Claude Code to Hermes — a different direction entirely).

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

**jq is required.** An earlier revision of this document said it was not, on the
grounds that the single hook using it had been rewritten to use the venv Python.
That was wrong: `hooks/discipline/grep-guard.sh`, `edit-surface-guard.sh` and
`unpushed-warn.sh` all parse their payload and emit their decision with `jq`, and
`install-reliability.sh` uses `jq` to wire them into `settings.json`. With jq
absent none of that errors — see "Guards that fail open" below.

Hooks do not inherit the user PATH reliably; `scripts/win/hook.sh` and
`scripts/win/run-job.sh` each prepend `.venv/Scripts`, `C:\util\apps\jq` and
`C:\util\apps\uv` for this reason.

## SQLite: the vendored pysqlite3 pin is moot here

`pyproject.toml` pins a vendored pysqlite3 wheel built against SQLite 3.51.3 to
dodge a WAL data-race present in 3.7.0–3.51.2. That wheel's marker scopes it to
`linux/x86_64`, so on Windows `uv sync` correctly falls back to the PyPI
pysqlite3 (3.51.1) — **and never activates it**, because no
`_pysqlite3_patch.pth` is generated. The venv therefore uses stdlib `sqlite3`,
which the uv CPython 3.11.15 links at **3.53.1** — already past the fix.

Consequence: `healthcheck.sh` asserted `sqlite_version == 3.51.3` exactly, so a
*strictly safer* SQLite failed the check. The assertion is now `>= 3.51.3`,
matching the stated intent ("WAL data-race fix present"). Do not re-tighten it to
equality.

## Hook wiring

All hooks live in `.claude/settings.json` (project scope) and route through one
dispatcher, `scripts/win/hook.sh <action>`:

```
C:/util/apps/Git/bin/bash.exe C:/opt/proj/Uncle-J-s-Refinery/scripts/win/hook.sh <action>
```

The dispatcher exists because (a) `bash` is not on the Windows PATH, so the
interpreter must be named absolutely, and (b) several original hooks relied on
shell redirection (`>> log 2>&1`, `2>/dev/null || true`) which is silently
dropped when settings.json invokes a script directly — there is no shell to
interpret it.

`.claude/settings.json` also sets `MSYS=winsymlinks:nativestrict`, without which
`skill-link.sh` degrades symlinks to directory copies. Native symlinks require
Windows Developer Mode (or an elevated shell).

### Hook shell — confirmed

Claude Code's hook runner shell on win32 was initially an assumption.
`scripts/win/shell-probe.sh` runs on SessionStart and appends to
`state/win-port-probe.log`; it reports `bash 5.3.15(1)-release` on
`MINGW64_NT-10.0-26100`. **The hooks do run under Git Bash** and the command
format is correct. Safe to delete the probe.

The same probe caught what the assumption hid: `uv`, `uvx` and `jq` all resolved
MISSING in the hook environment even though `C:\util\apps\uv` was already on the
user PATH. Hooks do not reliably inherit it. `hook.sh` and `run-job.sh` now
prepend the needed directories themselves.

## The POSIX venv shim

About 20 call sites across `install.sh`, `healthcheck.sh` and `scripts/` hardcode
`$ROOT/.venv/bin/<tool>`. Rather than rewrite each, `scripts/win/venv-compat.sh`
recreates the layout they expect:

- `.venv/bin` → symlink to `.venv/Scripts` (MSYS appends `.exe` on exec, so
  `.venv/bin/jcodemunch-mcp` resolves to `jcodemunch-mcp.exe`)
- `.venv/Scripts/python3.exe` → copy of `python.exe` (POSIX venvs expose `python3`)

`.venv/` is gitignored, so **both are destroyed by any venv rebuild** (`uv sync`,
`uv venv`). `hook.sh autofix` therefore re-asserts them on every SessionStart.
Run `bash scripts/win/venv-compat.sh` manually after a rebuild outside a session.

`.mcp.json` deliberately points at the explicit `.venv\Scripts\*.exe` paths rather
than the `bin` shim: Claude Code launches MCP servers via `CreateProcess`, not
through bash, so neither the `.exe` suffixing nor the directory symlink can be
relied on there.

## MCP server registration

`.mcp.json` (project scope) registers three servers. Their CLIs are **not**
uniform — this is the single easiest thing to get wrong:

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

MSYS ships no `flock`. Every `flock -n` guard therefore returned non-zero and took
its "already running" branch, so the guarded work was skipped while callers
reported success. This was not a Windows-only cosmetic issue; it silently disabled
real work:

- `scripts/jcodemunch-reindex.sh` — skipped the reindex, logged `reindex: OK`
- `scripts/jdocmunch-reindex.sh` — same
- `scripts/telegram-gateway-poll.sh` — exited every run, so the gateway never polled
- `scripts/memweave/sync_memory.sh` — skipped every sync
- `scripts/session-start-autofix.sh` — skipped the async stack upgrade

All now use an atomic `mkdir` lock directory with an `EXIT` trap, which needs no
external binary and behaves identically on Linux.

## Path-comparison correctness

`scripts/win/checkpoint.sh` replaces an inline hook that compared
`git rev-parse --show-toplevel` against the literal `/opt/proj/Uncle-J-s-Refinery`.
That guard never matched on Windows (git reports `C:/opt/proj/...`) — **and the
comparison was fragile on Linux too**.

String normalisation is not sufficient: under MSYS one directory has several
spellings (`C:/x`, `/c/x`) and mount aliases rewrite more
(`C:/Users/<u>/AppData/Local/Temp` → `/tmp`). The check now uses `[ a -ef b ]`,
comparing device+inode, which is spelling-proof and correct on both platforms.

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

The 7 cron jobs are **no longer Linux-only** — see "Scheduled jobs" below.

`healthcheck.sh --quick` goes 21 failures → 8 → **ok**. The 8 were not broken
components; they were the checker asserting a Linux install. `healthcheck.sh` is
now platform-aware: it probes `schtasks` instead of `crontab` on Windows, treats
unregistered supplementary MCP servers as `--` rather than failures, and honours
`state/disabled-features`.

## Guards that fail open

The three discipline hooks parse their payload and emit their decision with `jq`.
With jq absent:

- `grep-guard.sh:19` — `jq … 2>/dev/null || true` leaves `CMD` empty, the guard
  has nothing to match, and it exits 0. Claude Code reads no-decision as **allow**.
- `edit-surface-guard.sh` — documented FAIL CLOSED, but every deny comes from
  `jq -n`. Without jq the deny prints nothing and the edit proceeds. Fail-closed
  inverts to **fail-open**, which is worse than no guard.
- `install-reliability.sh:107-138` uses jq to *do the wiring* and warns-and-
  continues on failure, so the guards were never in `settings.json` at all.

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

Registration goes through `schedule-tasks.ps1`, not `schtasks.exe`, for one
reason: **schtasks has no flag for `StartWhenAvailable`, and the default is
false.** A job whose start time passes while the machine is asleep is skipped,
not deferred — so registering via schtasks yields four tasks that never fire on a
workstation. Two further traps:

- `schtasks /query` from Git Bash arrives as `C:/util/apps/Git/query`; MSYS
  rewrites arguments that look like POSIX paths. Use `MSYS2_ARG_CONV_EXCL='*'`.
- Under `set -o pipefail`, `printf "$big" | grep -q X` returns **failure on a
  successful match**: `grep -q` exits at the first hit, closes the pipe, and the
  still-writing `printf` takes SIGPIPE. Harmless against `crontab -l`; against
  schtasks' ~75KB it reported every registered job as missing. Use
  `[[ "$haystack" == *"$needle"* ]]`.

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

`pytest` — 585 passed, 106 failed. **All 106 failures are pre-existing**, verified
by running the identical subset against a pristine `HEAD` worktree and getting
identical counts. They are skill-frontmatter assertions (`test_skills.py`, 45) and
`test_session_end_check.py` plus siblings (61). No Windows change introduced a
regression.

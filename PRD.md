# PRD — Uncle J's Refinery maintenance

> This is the stable memory for a Ralph loop. The agent re-reads this
> file every iteration. Keep it structured. Update the Progress section
> at the end of each iteration.

## Goal

Keep the Uncle J's Refinery glue repo in a reproducible, cross-platform,
one-shot-install state. Every change that lands on `main` MUST leave the
repo such that, on a fresh Debian 13 / Ubuntu 24.04 / Windows 11 machine,
a user can run `prerequisites → install → verify → install-reliability →
install-guardrails → install-langfuse` in order and end up with:

- All seven MCP servers connected at user scope, pointing at the stack
  venv binaries (not `uvx`-cached copies) where a venv binary exists
- Claude Code's `~/.claude/settings.json` env block containing
  `MCP_TIMEOUT=60000`, the `LANGFUSE_*` keys, and `TRACE_TO_LANGFUSE=true`
- Langfuse running on `http://localhost:3050` with all six containers
  healthy, and `claude -p "test"` producing a trace in the UI within
  seconds
- All hooks from jCodeMunch and dwarvesf/claude-guardrails active and
  firing

## Non-goals

- Changing what the Refinery *is*. New third-party tools, new layers, or
  new MCP servers are out of scope unless the handoff or an explicit
  user ask adds them.
- Rewriting upstream code. We do not fork `claude-code-langfuse-template`
  or `claude-guardrails`; we patch their clones from our installer side
  only.
- Making the install work on Windows XP, Python 3.10, or other
  unsupported baselines.
- Moving `main` via force-push. Recovery from mistakes uses `git revert`.

## Context and prior work

- Repo: `williamblair333/Uncle-J-s-Refinery` on `main`.
- Handoff history lives in `HANDOFF.md`. New work-log entries are
  appended there under an `Overnight work log — YYYY-MM-DD` heading.
- Recent themes and decisions:
  - **Langfuse ClickHouse `std::stof("")` crash** on Linux 6.18 Liquorix.
    Fix: `:24.8` pin + bind-mount of `max 100000` over
    `/sys/fs/cgroup/cpu.max`. Version pin alone does NOT fix it —
    confirmed with `:24.12` and `:24.8` both crashing identically.
    Lives in `install-langfuse.sh`.
  - **PEP 668** blocks `pip install langfuse` on Debian 13. Install into
    the stack venv (`.venv/bin/python` via `uv pip install --python`)
    instead. Stop hook is registered with the venv interpreter so the
    SDK is resolvable when the hook fires.
  - **`jcodemunch-mcp init` regression**: it self-registers as
    `uvx jcodemunch-mcp` in Claude Code, and `claude mcp add` silently
    skips pre-existing entries. `install.{sh,ps1}` now wraps add in a
    `remove`→`add` helper to force convergence on the venv binary.
  - **`MCP_TIMEOUT`**: previously only in the README as a manual
    `.bashrc` edit. Now written into `~/.claude/settings.json` env block
    by `install.{sh,ps1}`.
  - **`mcp-clients/*.json`** used to hardcode one Windows user's venv
    path. They're now `*.json.tmpl` templates with `{{STACK_VENV_BIN}}`
    and `{{EXE}}` placeholders, rendered at install time to gitignored
    `*.json` outputs. Both installers know how to render.
  - **File modes**: five scripts were tracked as `100644` and threw
    "Permission denied". Now all `*.sh` are `100755` via
    `git update-index --chmod=+x`.
- MemPalace: check it for prior-art on any change before writing code.
  "Have we solved this before?" is question #1.

## Acceptance criteria

The done-gate exits when **all** of these pass. Copy this block into
the Progress section and tick off as you verify.

- [ ] The specific task asked of this iteration has a concrete, verified
      outcome (not "should work", but "I ran X and got Y")
- [ ] `./prerequisites.sh` and `./install.sh --auto-register` run
      end-to-end without interactive prompts (on a machine where they
      already ran — idempotent re-run is the test)
- [ ] `./verify.sh` reports **all PASS**
- [ ] `claude mcp list` shows all 7 stack servers as `✓ Connected`,
      and `claude mcp get jcodemunch` reports the venv path
- [ ] `python3 -c "import json; print(json.load(open(f\"{__import__('os').path.expanduser('~')}/.claude/settings.json\"))['env']['MCP_TIMEOUT'])"`
      prints `60000`
- [ ] Langfuse stack healthy: `docker compose -f
      claude-code-langfuse-template/docker-compose.yml ps` shows all
      six containers `Up` and the four with healthchecks `(healthy)`
- [ ] `curl -s http://localhost:3050/api/public/health` returns
      `{"status":"OK",...}`
- [ ] A `claude -p "smoke"` session produces a new line in
      `~/.claude/state/langfuse_hook.log` and a new trace in the
      Langfuse API (`/api/public/traces?limit=1`)
- [ ] `git grep -iE "sk-lf-[a-f0-9]{16,}|PASSWORD=[a-zA-Z0-9]{8,}"`
      on the working tree returns nothing
- [ ] `get_pr_risk_profile` < 0.65 for the current diff
- [ ] No new untested symbols
- [ ] All changed symbols have tests where tests exist for that
      surface (install scripts are integration-tested by running them;
      Python helpers should have unit tests if any are added)

## Constraints

- Use **jcodemunch / serena** for code navigation. Never `Read` a whole
  source file to "see what's in it". For the routing policy, see the
  stack-routing section in `~/.claude/CLAUDE.md`.
- Run **MemPalace** search before substantive work. If prior-art exists,
  link it in the Progress entry.
- Touch the fewest symbols possible. Don't refactor "while you're in
  there". A bug fix is a bug fix.
- **Don't edit files inside `claude-code-langfuse-template/` or
  `claude-guardrails/`**. Those are upstream clones. Patches that need
  to survive a re-clone live in `install-*.sh` / `install-*.ps1`.
- **Don't disable the PreToolUse hooks** in `~/.claude/settings.json`.
  They are the enforcement layer.
- **Never commit secrets.** Before every push:
  `git grep -iE "sk-lf-[a-f0-9]{16,}|PASSWORD=[a-zA-Z0-9]{8,}"`.
  Expect zero matches.
- **Don't touch `git config`.** Use `GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL`
  env vars per commit if identity isn't set.
- Preserve the PowerShell/bash parity. Every fix that lands in
  `install.sh` has a mirror in `install.ps1`, and vice versa. If one
  platform's fix doesn't apply (e.g. cgroup), document why in a
  comment.
- Match existing style: `step`/`ok`/`warn` helpers, `step` headings as
  `==> ...`, no emoji in scripts.
- Commit messages: imperative, under 72 chars for the summary, optional
  body after a blank line. Include a `Co-Authored-By` trailer when an
  AI assistant contributed.

## Progress

<!--
The FIRST non-empty line here is what the done-gate reads.
Start with `DONE` (uppercase, standalone) to signal completion.
Otherwise prepend a one-line status for the latest iteration.
-->

(iteration log — newest on top)

- 2026-04-21 — Parity fix: added `git --version` check to `verify.sh` to
  mirror `verify.ps1`. Git is required by `install-reliability.sh` and
  `install-langfuse.sh` (both clone upstream). Ran `verify.sh`: all PASS
  including new `git available`.
- 2026-04-21 — Fix ralph-harness `--cwd` (unsupported by `claude` CLI) →
  subshell `cd` / `Push-Location`; route `step`/`ok` to stderr so harness
  chrome doesn't pollute parsed gate JSON. Also ignore per-project
  `mempalace.yaml`/`entities.json` (issue #185). `git grep` for secrets
  returns zero matches on the tree.
- 2026-04-21 — Added `*-installer.txt` to `.gitignore` so installer
  transcripts (which embed generated Langfuse secrets + admin password)
  can't be accidentally committed. Verified with `git check-ignore -v
  ujr-linux-installer.txt` → matched at `.gitignore:107`.
- 2026-04-21 — Initial PRD created from HANDOFF.md work through that
  session. Baseline acceptance criteria checked on the live box at
  session end: all 7 MCP connected, MCP_TIMEOUT=60000, Langfuse healthy,
  trace roundtrip verified.

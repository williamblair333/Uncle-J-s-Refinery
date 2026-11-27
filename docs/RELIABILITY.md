# Reliability layer reference

The core stack gives Claude the right tools. The reliability layer makes sure Claude actually uses them correctly: it catches mistakes and checks the work before Claude calls it done.

The jMunch trio, Serena, Context7, and DuckDB run as MCP servers. These programs give an assistant tools it can call to do work outside the chat. The stack also includes memweave, an offline tool Claude runs from the command line to search past work.

| Component                     | What it does                                                      | When to turn off            |
| ----------------------------- | ----------------------------------------------------------------- | --------------------------- |
| prior-art-check skill         | Searches past work with memweave (mw_search.py) before the first real tool call of each session | Never. It only reads.   |
| judge skill                   | Checks what a change could affect and how risky the pull request is, then calls in specialist reviewers | for throwaway prototyping  |
| referee skill + `scripts/referee.py` | Asks Gemini through agy to review Claude's work. Returns a JSON verdict. If the review fails to run, approval is withheld. | when quota is short or the work is private |
| verifiable-task skill         | Write a check before handing off work. Run it yourself and report what it measured. | Never. It is a way of working. |
| Specialist agent (1)          | Reviews code for problems such as failures that go unreported and unsafe shell commands or child processes (five ECC agents dropped 2026-10-23) | per logic-changing edit |
| Ralph harness                 | Repeats the task until risk is low and the project requirements document (PRD) says the work is done    | only in live runs           |
| dwarvesf claude-guardrails    | Blocks pasted credentials and scans tool results for text that tries to give Claude instructions       | never (low cost, high value)|
| Superpowers plugin            | 20+ skills: brainstorm, systematic-debug, TDD, verify-before-done | if total skill count > 25   |
| Ralph Wiggum plugin           | /ralph slash command (Anthropic official version)                 | --                          |
| outcomes skill (--rubric)     | Grades each Ralph iteration against written criteria, starting with a fresh conversation   | when not using --rubric flag |
| refinery-doctor.sh            | Config drift detection: env key renames, stale MCP scopes, CLAUDE.md sync, placeholder values; `--fix` applies atomic migrations | after fresh install confirms all green |
| commit doc gate (`scripts/commit-doc-guard.sh`) | PreToolUse(Bash): blocks a real `git commit` in this repo (or a linked worktree) until `.session-end.yml` mandatory docs are staged; ignores read-only git calls and nested independent clones | never; fails open on bad input |
| Telegram multi-agent routing  | `/work <msg>` → project-context Claude (proj_root cwd, CLAUDE.md loaded); unqualified → restricted default (cwd=/tmp, disclosure ban); config in `config/telegram-agents.toml`; hardcoded fallback if TOML missing | never; missing TOML = safe restricted-only mode |
| ralph / Telegram billing      | Strip `ANTHROPIC_API_KEY` + `ANTHROPIC_AUTH_TOKEN` from subprocess env so `claude -p` uses OAuth subscription auth (Agent SDK credit, effective 2026-06-15: Pro=$20/mo, Max5x=$100/mo, Max20x=$200/mo); `--use-api` flag restores API billing for heavy parallel runs | never strip before 2026-06-15 |
| session-status-briefing skill | Step 3 runs `git fetch origin main && git log HEAD..origin/main` — reports if local is behind remote before any work starts (stale-code detection); fetch failure is surfaced via 2>&1, not swallowed | never; offline-safe (fetch error shown, briefing continues) |
| push-guard                    | `hooks/discipline/push-guard.sh` (PreToolUse Bash) blocks direct pushes to main/master/production. Replaces the inline regex from upstream dwarvesf/claude-guardrails, which matched raw text and so had no idea *which* command was running — it blocked feature-branch pushes when a later command said `main`, and blocked a `git commit` whose message described a push. Now tokenises with `python3`+`shlex`, splits only on **unquoted** separators, and judges ref tokens by their **last component** (keeps `restore/main-*` allowed, catches `HEAD:main`). Fails **closed**: unparseable quotes or a missing `python3` fall back to the regex, never to allow. `grep -qi push` prefilter keeps the interpreter off the hot path (~15.5ms vs ~2.5ms, and PreToolUse fires on every Bash call). **Re-running `install-guardrails.sh` restores the upstream buggy version** | never; 41 tests + CI job guard it |
| origin/main regression detector | `scripts/check-origin-main-regression.sh`, run from the SessionStart hook. Verifies the *outcome* the ruleset is supposed to guarantee, so detection survives the ruleset being disabled or absent elsewhere. Signal is **non-fast-forward** (current `origin/main` is not a descendant of the baseline in `state/origin-main-last-seen.sha`), **not** "local ahead of remote" — that is just unpushed work. Alerts to the session banner *and* `state/origin-main-regressions.log`. Offline/auth/timeout → logged skip, never a false alarm. **`state/origin-main-last-seen.sha` is evidence, not cache — deleting it disarms detection silently** | never; it is read-only against the remote |
| `main` branch ruleset         | GitHub ruleset `protect-main-no-force-push` (id `20854165`): `non_fast_forward` + `deletion`, `enforcement: active`, `bypass_actors: []`, `current_user_can_bypass: "never"`. Exists because `origin/main` was force-reset to `f3a7ed9` **five times** (2026-08-04 → 2026-08-14) by a second clone pinned at that commit, silently destroying PRs #100–#105. Applies to the owner — a deliberate force-push requires disabling the ruleset first. Verify with `GET /repos/:owner/:repo/rules/branches/main`; **`git ls-remote`, never `gh pr list` or `git branch -a`, is the authority on remote ref state** | never; disable only for an intentional history rewrite, then re-enable |
| force-rules engine            | `scripts/force-rules.sh` (global sync Stop hook) blocks turn-end until every `scripts/force-rules.d/*.sh` rule verifies against the transcript. Anti-brick: `stop_hook_active` backstop (blocks at most once per stop-chain) + 5-block cap + fail-open on any error; the anchor excludes the hook's own injected feedback (else it perpetually re-blocks). Enforcement = one forced retry, not block-until-complied. Add a rule = drop one `*.sh`. **Currently ruleless/inert** (terse-reply rule removed) | disable a rule: remove its file; disable engine: remove the Stop hook |

## How the pieces compose

```
── SESSION START ──────────────────────────────────────────────────────
SessionStart hooks
   ├── healthcheck context injected into session banner
   └── skill-link: per-project skills symlinked to ~/.claude/skills/

── PER-MESSAGE LOOP ───────────────────────────────────────────────────
user message
   │
   ▼
UserPromptSubmit: scan-secrets.sh      <- blocks pasted credentials
   │                                      (API keys, tokens, PEM blocks)
   ▼
prior-art-check skill                  <- "have we solved this?"
   │   memweave hit? surface prior decisions as context
   ▼
CLAUDE.md routing policy               <- which MCP tool fits?
   │
   ▼
MCP tools / main work                  <- jcodemunch / serena / jdatamunch
   │                                      jdocmunch / context7 / duckdb (+ memweave CLI)
   ▼
PreToolUse hooks                       <- enforce-docs, scan-commit,
   │                                      bash-guard rules, jcodemunch pre-hook
   ▼
[Edit or Write?]──no──────────────────────────────────────────────┐
   │ yes                                                           │
   ▼                                                              │
judge skill                            <- get_blast_radius,        │
   │                                      get_changed_symbols,     │
   │                                      get_pr_risk_profile      │
   ▼                                                              │
specialist agents (risk-based)         <- see trigger matrix below │
   │   verdict: approve / concerns / block                        │
   ▼                                                              │
tool executes ◄────────────────────────────────────────────────────┘
   │
   ▼
PostToolUse (Edit/Write): jCodemunch auto-reindex
PostToolUse (Read/WebFetch/Bash/mcp): injection defender
   │
   ▼
response to user

── SESSION END ────────────────────────────────────────────────────────
Stop hooks (in order)
   ├── Langfuse trace submitted                       (global settings.json)
   ├── session-end-check.sh --stop-hook               (global — doc gate)
   ├── unpushed-warn.sh + pr-check.sh                 (global — reminders)
   ├── session-notify.sh  (Telegram, opt-in)          (project settings.json)
   ├── memweave/sync_memory.sh '' 15  (incremental ingest of recent transcripts)
   └── skill-suggest.sh + skill-link unlink
```

On a typical coding turn, all the checks can run in under 15 seconds.
Ralph repeats the per-message loop on every iteration.

## Deploying the routing policy to `~/.claude/CLAUDE.md`

Keep the Dreaming Notes when you update the installed routing policy.
`features/dreaming/dream.sh` appends a `## Dreaming Notes (auto-generated)`
section to `~/.claude/CLAUDE.md`. The playbooks in that section live only
in the installed file. A wholesale `cp repo → installed` deletes them.

The same kind of overwrite erased the global-only "Docker Port Registry" section.
`scripts/audit/components.json` still lists "Docker Port Registry" as a routing-policy heading. That heading now appears zero times in either policy file.

| Writer | Behaviour |
|--------|-----------|
| `refinery-doctor.sh --fix` | Rebuilds the file as the repo policy (the prefix) followed by the installed copy's Dreaming Notes (the tail). Backs up to `${installed}.bak`. Compares only the policy prefix, so an appended tail is not reported as permanent drift. |
| `install.sh` §6b | Delegates to the above. Its one remaining `cp` is the create-when-absent branch. With no doctor present it leaves an existing file alone rather than copying over it. |
| post-merge git hook | Notifies only — `CLAUDE.md updated — copy to ~/.claude/CLAUDE.md if you use global routing`. Nothing auto-deploys. |

When you edit either writer, keep these two things intact:

- **Keep the marker strings identical.** Exactly two files define the marker
  (`dream.sh` and `refinery-doctor.sh`). They are independent copies.
  `install.sh` delegates to the doctor and holds no third copy. If the strings differ, the doctor silently falls back to comparing the whole file. It then reports drift forever and rewrites the file on every run.
- **Treat exit status 1 as an applied migration.** `refinery-doctor.sh` exits 1 when it applied a migration. That includes `--fix`, where exit 1 is the normal success result. `install.sh`
  runs `set -euo pipefail`, so it captures the status in `_doctor_rc`
  (0 = in sync, 1 = applied, other = real failure). Otherwise, a successful fix
  stops the installer at §6b and skips every later section. Don't replace this with a bare `|| true`. That hides real crashes.

`tests/test_claude_md_deploy.py` checks this behavior. The original bug shipped
because CI never runs `install.sh`. The test also checks the source of §6b directly.

## memweave memory freshness

Claude searches past work to answer "Have we solved this before?"
`CLAUDE.md` §4 routes that search to `scripts/memweave/mw_search.py`.
It runs offline and reads the store without changing it. It combines semantic search, which looks for similar meaning using a local ONNX model (a portable model file format), with BM25, which ranks
matches based on the words they share.

The store at `~/.uncle-j-memory` covers every project under `~/.claude/projects`.
It keeps transcripts as Markdown files and uses a SQLite index to search them.
The `uncle-j` name is left over from an earlier setup.

Two callers run `scripts/memweave/sync_memory.sh`. To keep them from writing
to SQLite at the same time, the script claims a lock with an atomic
`mkdir "$LOCK.d"` (`/tmp/memweave-sync.lock.d`). Only one process can create
that directory. It doesn't use `flock`, because MSYS/Git Bash ships without it. That's why the script uses a `mkdir` lock.

| Caller | Schedule | Scope |
|--------|----------|-------|
| `uncle-j-memweave-sync` cron | 02:30 nightly (`nice -19`) | `--all` — full cross-project export+index (every project) |
| Stop-hook (`# uncle-j-memweave-sync`) | end of every session **whose cwd is this repo** (`async`) | incremental — this repo, `LIMIT 15` most-recent transcripts |

The Stop hook refreshes only this repo's memory. Understand why before adding a third caller. Each project registers its
hooks in its own `.claude/settings.json`. A hook runs only when the project
is the session's current working directory. With an empty `PROJECT` argument,
`sync_memory.sh` takes the project name from the script's location. The first hook therefore always imports `-opt-proj-Uncle-J-s-Refinery`, whichever project the session was working on. On 2026-08-19,
the count was 297 hook runs, all for that project, and 45 nightly `--all` runs.

Other projects rely on the nightly cron job, a scheduled task. Their memory
can lag by up to ~24h. The Obsidian vault at `/opt/proj/jaredrhod` had its own
hook from 2026-08-19 until the vault was archived on 2026-11-22. Its settings
entry is dormant.

This race is left unfixed on purpose. If two sessions close seconds apart, one hook can miss the `mkdir` lock.
It exits 0 and logs `sync skipped — another sync holds`. The 02:30 cron run
picks up the deferred work. The hook doesn't queue or retry. Waiting for the lock while the session closes would be worse than syncing a few hours later. The log records what happened.

The hook and cron job both send output to `state/memweave-sync.log`. The script
writes to standard output and standard error, so each caller chooses where
those messages go. If a sync is interrupted, the Markdown files are enough
to rebuild the index (memweave M2 crash recovery). Remove the index with
`rm` and the rebuild produces the same bytes.

### The corpus

Most files in `~/.uncle-j-memory/memory/*.md` are copies of Claude transcripts.
`sync_memory.sh` uses `export_transcripts.py` to recreate them. Keep the
dream-synthesis notes that `dream.sh` copies in and `premortem-audit.md`
when cleaning up `memory/`. A transcript export cannot restore either.

From 2026-08-19 to 2026-11-22, `mirror_vault.py` also copied the Obsidian
vault into `memory/vault/`. The mirror was removed because searches made old
notes look like current decisions. The vault's priorities were last edited
on 2026-08-22. Decisions now live in each repo's HANDOFF and ROADMAP files
and in Claude's memory notes. The vault is archived in place. Git history
holds `mirror_vault.py` and its tests.

Set up the py3.12 environment `.venv-memweave` on a fresh install.
Memweave requires ≥3.12, and the project environment uses 3.11.
Without its own environment, `sync_memory.sh` logs an error and exits 1.
`install.sh` registers the cron job. Create the environment by hand until
the installer can do it (Phase 3/4).

There is no freshness alarm yet. Failures go to the log. A hung export holds
the lock, so later runs skip while the store grows stale. The open follow-up
is to have `healthcheck.sh` check that the index's modification time is less
than 48h old.

## retrieval index freshness

A stale index can give Claude an old answer that looks current.
`CLAUDE.md` sends code searches to jcodemunch and document searches to
jdocmunch before falling back to `Read` or `Grep`. Scheduled jobs refresh
both indexes, and `healthcheck.sh` checks their freshness.

| Index | Refresh | Gate | Failure key |
|-------|---------|------|-------------|
| jcodemunch (`~/.code-index`) | `uncle-j-jcodemunch-reindex` 01:00 + `jcodemunch-watch.service` | `state/jcodemunch-last-indexed.sha` vs git HEAD | `jcodemunch-index-stale` |
| jdocmunch (`~/.doc-index`) | `uncle-j-jdocmunch-reindex` 01:30 + `post-merge-hook.sh` (this repo only, on `*.md` change) | per-repo manifest `head_sha` vs source root HEAD | `jdocmunch-index-stale` |

`scripts/jdocmunch-reindex.sh` reads the list of source folders from
`~/.doc-index/local/<name>.json`. It checks several folders (9 currently),
most outside this repo. For a Git folder, it compares the latest commit
(HEAD) with the saved `head_sha`. For other folders, it compares the newest
file modification time with `indexed_at`. It rebuilds only stale indexes,
so there is almost no nightly work when nothing changes.

The script uses `flock` to keep runs from overlapping. It skips a repo when
jdocmunch holds its `.json.lock`, and it continues if a source folder has
disappeared. It exits 2 if the manifest's `index_version` is a version it doesn't know how to read.
The health check fails only for this repo's index. The other eight produce
warnings.

On 2026-07-18, the old check was still running `ls ~/.doc-index | wc -l`
to report "N repo(s)." The directory always had two entries (`local/` and
`_savings.json`), even if the index was empty. The check kept reporting
`OK 2 repo(s)`. It never read a date, so it could never fail. A check that can't fail is worse than no check: it turns "unknown" into false confidence. Here the false OK was taken as evidence and led to a wrong diagnosis. Prefer checks that test a property over checks that count things.

`scripts/post-merge-hook.sh` refreshes jdocmunch when a merge changes
`*.md` files. It uses `--path "$PROJ_ROOT"`, so it covers this repo. It covers none of the other eight, and it runs only on merges, not on edits.
That kept this repo's index current through merges while the other eight
fell weeks behind. The nightly job extends this to the other sources. Keep both: the hook isn't redundant.

The open follow-up is to wire up `jdocmunch-mcp hook-posttooluse`. Like the
jCodemunch PostToolUse hook, it would refresh the index after edits, even
when they never reach a merge.

## What each component buys you

### prior-art-check

Before working on a non-trivial prompt, Claude uses `mw_search.py` to
check whether someone has already solved the problem. The lookup has zero
cost with an empty store and adds 1-2 seconds when the store is warm.

In step 3b, Claude checks any search result containing `pending`, `awaiting`,
`needs`, `consider`, `not yet`, `TODO`, or `FIXME` against the current
source before treating it as fact. For example, a memory entry might say
"PR awaiting review" long after the pull request has merged and the fix is
running. The startup health check flags the same entries as warnings.

### judge

Judge runs before any non-trivial Edit or Write. It checks what the change
could affect and sends the work for specialist review.

1. Gather evidence from jCodemunch with `get_blast_radius`, `get_changed_symbols`, `get_untested_symbols`, and `get_pr_risk_profile`.
2. Choose reviewers based on that evidence. The table below lists what triggers a review.

It catches four common mistakes.

1. Calling an invented function, such as `foo.bar()` when `bar` is missing.
2. Importing a module the project does not depend on.
3. Leaving out a required argument.
4. Renaming something and missing a place that calls it.

Skip Judge for typos, formatting, comments, or a single variable rename
with no logic change. Also skip it if the change has already been reviewed
in the same turn.

### Specialist agent trigger matrix

One agent in `global-agents/`, symlinked to `~/.claude/agents/`. Six ECC agents were imported
2026-05-22; on 2026-10-23 five were dropped or merged (decisions below).

| Agent | Spawn when | Skip when |
| ----- | ---------- | --------- |
| `code-reviewer` | Edit/Write changes function logic, adds/removes functions or classes, modifies control flow, touches API or data model, error handling, subprocess, network/file I/O or cron/hook scripts | Typos, whitespace/formatting, comment-only, single-variable rename with no logic change |

| Former agent | Decision | Why |
| ------------ | -------- | --- |
| `silent-failure-hunter` | merged into `code-reviewer` | Its 40 lines were a checklist; as its own agent it fired on the same edits as code-reviewer, a second pass per change. |
| `security-reviewer` | dropped (shell/subprocess patterns merged into `code-reviewer`) | npm/eslint/OWASP-web workflow for a Python+bash repo, and it held Write/Edit as a *reviewer*. Deep passes: `red-team` / `blue-team` skills, `/security-review`. |
| `planner` | dropped | Same job as `superpowers:writing-plans` and the built-in Plan agent; Opus per spawn; Stripe/Next.js worked example; no jcodemunch tools. |
| `architect` | dropped | Generic SaaS patterns (Next.js, Redis, Supabase); `superpowers:brainstorming` covers design choices here. |
| `tdd-guide` | dropped | Duplicates `superpowers:test-driven-development`; mandates 80% coverage and Playwright E2E (Microsoft; avoided here). |

### Ralph harness (our version vs. the plugin)

Anthropic's Ralph plugin (`/ralph`) follows the Huntley pattern. It gives
the agent the same prompt file until the agent says the work is done.

`ralph-harness.sh` checks the change before accepting that answer.

- `get_changed_symbols` confirms that the code changed.
- `get_untested_symbols(changed_only=true)` blocks completion if new code has no tests.
- `get_pr_risk_profile` blocks completion if the combined risk score exceeds the limit.

The harness stops only when the agent says "done" and the checks agree.
Use the plugin to explore an idea. Use the harness for changes you plan to
commit.

### Outcomes grader

The `outcomes` skill reviews the work in a fresh context window. It starts
without the working agent's conversation history, so it can catch details
the agent has come to take for granted.

`ralph-harness.sh --rubric <path>` runs the grader after each iteration.

1. Read the rubric, which lists what counts as a pass for each criterion and how much it matters.
2. Check each criterion against the PRD Progress section and the repo. The PRD describes the work the project calls for.
3. Return a JSON verdict, `pass` or `fail`, with specific fixes when needed.
4. On `fail`, pass the report to the next iteration.

Completion requires the grader and the harness checks for risk and test
coverage to agree. `OUTCOMES_MAX_ITERATIONS` caps the run at 5 iterations
by default. On fresh installs, `install-reliability.sh` sets it in the
`env` block of `~/.claude/settings.json`. For a single run, use
`export OUTCOMES_MAX_ITERATIONS=N` before starting the harness.

The rubric template lives at `global-skills/outcomes/RUBRIC.md.template`.
Put a project rubric at `.claude/outcomes/rubric.md` in that repo.

### Superpowers

Superpowers is the single biggest agent-reliability upgrade available in 2026. Its 20+ skills enforce the steps an agent might otherwise skip, from clarifying the request to proving the fix works.

- `brainstorming` forces Claude to clarify requirements before coding.
- `systematic-debugging` uses a 4-phase process to gather evidence and find the cause before trying a fix.
- `test-driven-development` starts with a failing test, adds code to make it pass, then tidies the code.
- `verification-before-completion` requires the agent to prove the fix works before claiming success.
- `requesting-code-review` helps the agent hand off a change to a reviewer. It pairs with Judge.

The Claude Code community suggests keeping at most 20-25 skills active.
Every active skill uses up context, and going past 25 makes Claude pick skills badly. Superpowers adds 20+ on
its own, so remove skills you do not use after installing it.

### dwarvesf/claude-guardrails

Guardrails run as hooks, actions that Claude Code triggers at set points.

- **UserPromptSubmit** checks your prompt for credentials before it reaches the model. It blocks live AWS keys, GitHub, Anthropic, and OpenAI tokens, PEM blocks, and BIP39 recovery phrases. Blocking them keeps them out of the model's input and the session log.
- **PostToolUse** checks Read, WebFetch, and Bash output for known prompt-injection patterns. Prompt injection is text that tries to give the assistant instructions from inside a file, page, or tool result. The scanner warns but doesn't block, so people can still work with legitimate security material.

The checks draw on research from Trail of Bits and Lasso and on Anthropic's
security documentation. They add little overhead. Always keep them on.

## Tier 2 — mentioned, not installed

If you want more later, these are the next things worth adding:

- **Langfuse** (https://langfuse.com) — agent observability. Native
  Claude Agent SDK integration. Every tool call and completion becomes
  an OpenTelemetry span. Self-hostable via Docker. 19k stars, MIT
  license. Best for "why did my agent do X two sessions ago."
- **Anthropic-Cybersecurity-Skills** (mukul975) — 754 skills mapped to
  MITRE ATT&CK / NIST CSF. Overkill unless you work in security.
- **Verdent Review Subagent** — commercial. Cross-validates a change
  with Claude + Gemini + GPT-5.2 concurrently. Expensive per review;
  use on high-stakes PRs only.

## Operational notes

The SessionStart staleness check scans `MEMORY.md` for stale tracking entries (`pending`, `awaiting`, `needs <verb>`, etc.) and flags them at session start so they're verified before being reported as current fact.

`session-end-check.sh` behaviour is covered by `tests/test_session_end_check.py` (10 tests, job 5 in `ci.yml`).

`install-reliability.sh` also provisions the jdocmunch-watch `--no-ai-summaries` systemd
drop-in (`scripts/jdocmunch-watch-dropin.sh`; workaround for upstream jdocmunch-mcp#120), and
`refinery-doctor.sh --fix` restores it (check `jdocmunch-watch-dropin`). It's skipped where
the watcher unit isn't installed. A drop-in that already sets the flag is never replaced.

(memweave memory operational details — freshness, store layout, recovery — are in the "memweave memory freshness" section above. mempalace was decommissioned 2026-06-13; with it gone, the `chromadb==1.5.8` HNSW-corruption-workaround pin + `chroma-hnswlib` dep were also removed from `pyproject.toml` — chromadb was a mempalace-only transitive dependency.)

### Guards that fail *open* (found during the 2026-07-30 Windows port)

Five scripts could skip all their work and still report success. They used
this pattern to avoid running twice at the same time.

```bash
exec 9>"$LOCK"
flock -n 9 || { log "Already running — skipping."; exit 0; }
```

MSYS/Git Bash ships without `flock`. The missing command and a held lock
both sent the script down the skip branch. Every run exited 0, so callers
reported success. `jcodemunch-reindex.sh` logged `reindex: OK` without
indexing anything. `telegram-gateway-poll.sh` exited every time, so the
gateway never polled.

All five scripts now claim an atomic `mkdir` lock directory. An `EXIT`
trap removes it when the script ends. The same pattern works on Linux.

```bash
if ! mkdir "$LOCK.d" 2>/dev/null; then log "Already running — skipping."; exit 0; fi
trap 'rmdir "$LOCK.d" 2>/dev/null || true' EXIT
```

Check that the guard itself ran before accepting its result. If a missing
tool looks like a successful check, the guarded work can disappear without
an error.

The port also turned up two hidden bugs that affected every platform, not just Windows. The PostToolUse
checkpoint hook compared `git rev-parse --show-toplevel` with a hardcoded
path and never ran. `healthcheck.sh` required an exact SQLite version, so
a newer, safer version failed the check.

See `docs/WINDOWS-PORT.md` for platform details.

---

## Skills

Skills live in `global-skills/` and are symlinked to `~/.claude/skills/` by `install-reliability.sh`. Any directory added to `global-skills/` is automatically picked up — no hardcoded list to maintain.

The `auto-maintain-commit-and-deploy` skill documents the pattern: dynamic glob replaces hardcoded name lists, and `git commit` is coupled with an immediate symlink pass so new skills are live before the next session.

---

## The hook-blocks log must stay parseable to be reviewable

`state/hook-blocks.log` is the audit trail for the discipline guards, and the weekly
review reads it one-entry-per-line. Guards append with `printf '%s' "$CMD" | tr '\n\r\t' ' ' | head -c N`
— **collapse whitespace before truncating, never after**. `head -c` cuts bytes, not
lines, so an unsanitised multi-line command writes N rows into the log and only the last
one carries its `session=` field. When this was found (2026-08-13) 385 of 3452 lines
were continuation junk, meaning the file over-reported its own entry count by 12% and
some blocks could not be attributed to a session at all.

Two properties follow, and both are worth preserving in any new guard that writes here:

- **Truncation is lossy for diagnosis.** A block truncated at 120 bytes can be
  permanently undiagnosable if the trigger sat past the cut. One of the 2026-08-13
  blocks is exactly this and cannot now be explained.
- **Verify the format, not just the count.** `awk '$0 !~ /^[0-9]{4}-[0-9]{2}-[0-9]{2} /'`
  over the log reports malformed lines directly; a plain `wc -l` silently counts the
  corruption as data.

- **Text only, or grep goes silent.** GNU grep treats a file holding one NUL byte or
  one invalid UTF-8 sequence as binary: `grep -c DATE` prints nothing and exits 1. The
  live log carried a run of 209 NULs (one contiguous block at byte 20047, between a
  2026-06-02 20:02 and a 2026-06-03 07:21 record: the zero-fill an unclean shutdown
  leaves, not hook output) and two lines where `head -c` had cut a multibyte character.
- **Rotation archives, never truncates.** The log is not reconstructible.

Since 2026-10-22 every hook that writes the log does it through one inline function,
`hook_log_append`, byte-identical in `grep-guard.sh`, `edit-surface-guard.sh`,
`surface-write-guard.sh` and (since 2026-10-31) `token-guard.sh` (`tests/test_hook_log.py`
pins the copies). It turns every C0
control byte and DEL into a space, drops invalid UTF-8, and past 1 MiB
(`HOOK_LOG_MAX_BYTES`) renames the log to `hook-blocks.log.YYYYMMDD` (or
`.YYYYMMDD-HHMMSS-PID` if that exists) under a `mkdir` lock, with `mv -n` so no archive
is ever overwritten. Readers must cover the archives: `collect_benefits.py` does
(`block_log_files`). Archives written before 2026-10-22 can still hold NULs, so read
those with `grep -a`.

`credential-guard.sh` still appends directly. Its fields are a fixed tool name, a
regex match of path characters and the session id, so it can't emit the bytes above,
but it does not rotate the log.

### Path guards must be spelling-independent

A PreToolUse guard receives the **raw, unexpanded** command string — `~` never arrives as
`/`. Any path test that matches only `/*` therefore treats `~/x.sh` and `/home/bill/x.sh`
as different files and can return opposite verdicts for the same target. That was PR
#106's bug, and it survived because `grep-guard.sh` had two path branches (recursive and
non-recursive) that drifted apart: one accepted `/*|"~"*`, the other only `/*`.

Two rules follow for any new or edited guard:

- **Expand, then test.** Substitute `$HOME` for a leading `~` and apply the same
  containment check to both spellings. Do not special-case `~` into a blanket allow — that
  converts a test into an escape hatch.
- **A guard with two path branches has two chances to drift.** If you touch one, check the
  other in the same edit, and add the case to `tests/test_grep_guard.py` in both forms.

Related caveat: `in_repo()` is a literal string-prefix test with no `realpath` resolution,
so repo source reachable through a home-directory symlink is allowed by *either* spelling.
This is a known open gap, tracked in ROADMAP — not a regression.

---

## A cron job that never succeeds looks like one that has nothing to say

The Sunday 08:00 stats job failed every week from install until 2026-10-18, and no one noticed.
`features/session-stats/stats.sh` asked Langfuse for `limit=500` when the
API allows at most 100. The server returned HTTP 400, and `curl -sf` hid
the error message. The script exited 22 and left only "Querying Langfuse"
in `state/stats.log`. A weekly report that never arrives looks just like a quiet week. The failure surfaced only because `scripts/cron_catchup.py` prints each job's exit code at boot.

- **Keep the server's error message.** Never use `curl -sf` against an API whose error message matters. `stats.sh` saves the HTTP status and prints the response body on failure.
- **Stay within the API's documented page limit, and page explicitly.** `stats.sh` reads `/api/public/traces` 100 records at a time. It stops after 50 pages and says when it has cut the results short.
- **Use a temporary file for bulk data.** Linux caps a single environment string at 128 KB. A week of traces (~400 KB) broke the old hand-off. `mktemp -d` creates a temporary directory and `trap … EXIT` cleans it up.
- **Remove columns that can only ever be 0.** The Claude Code Langfuse hook records no token usage, so the report dropped the Tokens column.

---

## A standing red check is worse than no check

`Skill frontmatter regression` failed on every pull request for so long
that ROADMAP listed the cause as "not readable without a token." The actual
cause was one skill with a category missing from `VALID_CATEGORIES`.

A check should help you tell whether a change broke something. While the
check stayed red, a new regression looked exactly like the standing
failure. Reviewers could not tell whether a pull request passed CI, the
automated checks that run on changes.

- **Fix or remove a check that fails every time.** Merging around it teaches people and agents to merge past any red check.
- **Before merging with a failed check, prove the failure is unrelated. Don't assume it.** The cheap proof: run the same test in a detached worktree, a separate checkout at the base commit. If it fails the same way there, the failure already existed. Record that you checked.
- **Read the job log before deciding why the check failed.** Here, `gh run view --log-failed` returned nothing. `gh api repos/<owner>/<repo>/actions/jobs/<id>/logs` returned the failed assertion.

---

## Disable / uninstall

```bash
# Remove our skills
rm -rf ~/.claude/skills/prior-art-check ~/.claude/skills/judge

# Remove dwarvesf guardrails (hooks get merged into settings.json; you
# need to edit that manually if you want to revert)
rm -rf /opt/proj/Uncle-J-s-Refinery/claude-guardrails

# Remove Superpowers / Ralph
# Inside claude: /plugin uninstall superpowers
# Inside claude: /plugin uninstall ralph-loop
```


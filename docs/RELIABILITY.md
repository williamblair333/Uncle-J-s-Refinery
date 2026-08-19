# Reliability layer reference

The core stack (jMunch trio + Serena + Context7 + DuckDB MCP servers, plus the
offline memweave memory CLI) gives Claude the *right tools*. The reliability layer
makes sure Claude *actually uses them correctly*. Four components:

| Component                     | What it does                                                      | When to turn off            |
| ----------------------------- | ----------------------------------------------------------------- | --------------------------- |
| prior-art-check skill         | memweave (mw_search.py) lookup BEFORE the first real tool call every session | never; it's just a lookup   |
| judge skill                   | Gathers blast radius + PR risk, then delegates to specialist agents | for throwaway prototyping  |
| Specialist agents (6)         | Code review, security, silent failures, planning, architecture, TDD — each with precise trigger conditions | individually per task type |
| Ralph harness                 | while-true loop that only stops when risk is low + PRD is DONE    | only in live runs           |
| dwarvesf claude-guardrails    | Block pasted secrets, scan tool output for prompt-injection       | never (low cost, high value)|
| Superpowers plugin            | 20+ skills: brainstorm, systematic-debug, TDD, verify-before-done | if total skill count > 25   |
| Ralph Wiggum plugin           | /ralph slash command (Anthropic official version)                 | --                          |
| outcomes skill (--rubric)     | Rubric-aware grader in fresh context after each Ralph iteration   | when not using --rubric flag |
| refinery-doctor.sh            | Config drift detection: env key renames, stale MCP scopes, CLAUDE.md sync, placeholder values; `--fix` applies atomic migrations | after fresh install confirms all green |
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

All gates can fire in under 15 seconds for a typical coding turn.
Ralph runs the per-message loop on every iteration.

## Deploying the routing policy to `~/.claude/CLAUDE.md`

The installed copy is **not** a mirror of the repo copy. `features/dreaming/dream.sh` appends a
`## Dreaming Notes (auto-generated)` section to `~/.claude/CLAUDE.md` and never to the repo copy,
so the playbooks under it exist in no other file. Any wholesale `cp repo → installed` deletes them.

That is how the global-only "Docker Port Registry" section was lost: `scripts/audit/
components.json` still lists it as a routing-policy heading, and it now appears zero times in
either file.

| Writer | Behaviour |
|--------|-----------|
| `refinery-doctor.sh --fix` | Rebuilds as repo policy prefix + the installed copy's Dreaming Notes tail. Backs up to `${installed}.bak`. Compares only the policy prefix, so an appended tail is not reported as permanent drift. |
| `install.sh` §6b | Delegates to the above. Its one remaining `cp` is the create-when-absent branch. With no doctor present it leaves an existing file alone rather than copying over it. |
| post-merge git hook | Notifies only — `CLAUDE.md updated — copy to ~/.claude/CLAUDE.md if you use global routing`. Nothing auto-deploys. |

Two things to preserve when editing either writer:

- **The marker string lives in exactly two files** (`dream.sh`, `refinery-doctor.sh`) and they are
  not linked. `install.sh` deliberately holds no third copy. A mismatch silently restores
  whole-file comparison, which reports drift forever and rewrites the file on every run.
- **`refinery-doctor.sh` exits 1 when it applied a migration**, including under `--fix` where that
  is the success path, and `install.sh` runs `set -euo pipefail`. The call site captures the status
  into `_doctor_rc` and dispatches on it (0 = in sync, 1 = applied, other = real failure).
  Unguarded, the installer aborts at §6b on a working fix and silently skips every later section.
  A bare `|| true` is not an acceptable substitute — it swallows genuine crashes.

`tests/test_claude_md_deploy.py` pins all of this. CI never executes `install.sh`, which is why the
original defect shipped unnoticed, so §6b's shape is additionally asserted at source level.

## memweave memory freshness

Project memory routing (`CLAUDE.md` §4) resolves "have we solved this before?" to
`scripts/memweave/mw_search.py` (offline ONNX semantic+BM25, read-only) over the store below.

The offline memweave store at `~/.uncle-j-memory` is the **cross-project** memory store — it
holds every project's transcripts under `~/.claude/projects` (markdown corpus + sqlite index),
not just this project's. (The `uncle-j` name is legacy.) It's kept current by two callers of
`scripts/memweave/sync_memory.sh`, which serialises on an atomic `mkdir "$LOCK.d"`
(`/tmp/memweave-sync.lock.d`) so the two can never race the single sqlite writer. It is **not**
`flock`-guarded — MSYS/Git Bash ships no `flock`, which is why the mkdir form was chosen:

| Caller | Schedule | Scope |
|--------|----------|-------|
| `uncle-j-memweave-sync` cron | 02:30 nightly (`nice -19`) | `--all` — full cross-project export+index (every project) |
| Stop-hook (`# uncle-j-memweave-sync`) | end of every session **whose cwd is this repo** (`async`) | incremental — this repo, `LIMIT 15` most-recent transcripts |
| Stop-hook (`# uncle-j-memweave-sync-vault`) | end of every session **whose cwd is `/opt/proj/jaredrhod`** (`async`) | incremental — `-opt-proj-jaredrhod`, `LIMIT 15`, **plus the vault mirror** |

Stop-hook reach is narrower than it looks, and the reason is worth understanding before adding a
third. The hooks are registered per-repo in each project's `.claude/settings.json`, not at user
scope, so one only fires when that project is the session's cwd. Worse, `sync_memory.sh` with an
*empty* `PROJECT` argument derives the slug from its own location — so the first hook always
ingests `-opt-proj-Uncle-J-s-Refinery` no matter which project the session was working on.
Measured 2026-08-19: 297 hook runs, all of them that project; 45 nightly `--all` runs.

The vault hook (added 2026-08-19) therefore passes its project **explicitly**. Without that it
would re-ingest this repo and leave the vault's own transcripts to the cron. Every project except
these two is still covered by the cron alone, with up to ~24h of lag.

**Known race, deliberately not fixed:** two sessions closing within seconds of each other means
one hook loses the `mkdir` lock and exits 0 with `sync skipped — another sync holds`. It does not
queue or retry, so that project's ingest defers to the 02:30 cron. The alternative — blocking on
the lock during session teardown — is a worse failure than a deferred ingest. The skip is logged,
so it is diagnosable after the fact rather than invisible.

Both hooks are asserted by `healthcheck.sh` (`check_vault_hook_registered`), which greps for each
marker separately. That matters: a hand-edit preserving the checkpoint hook and dropping the sync
hook would otherwise pass green, and a missing sync hook is invisible by construction — the corpus
just reverts to 24h staleness, and a stale prior-art miss reads exactly like a genuine
"no prior work".

Both redirect to `state/memweave-sync.log`; the script logs to stdout/stderr only (callers own
the destination). The store is fully reconstructable from the markdown corpus (memweave M2
crash-recovery: `rm` the index → byte-identical rebuild), so an interrupted sync is recoverable.

### Two corpus sources

`sync_memory.sh` writes two kinds of markdown into `~/.uncle-j-memory/memory/`, and both are
**derived** — the store is a cache of them, never the original:

| Source | Lands in | Written by | Holds |
|--------|----------|------------|-------|
| Claude transcripts | `memory/*.md` | `export_transcripts.py` | what was *said* — the conversations |
| Obsidian vault | `memory/vault/**` | `mirror_vault.py` | what was *decided* — VAULT-INDEX, Active Priorities, per-project notes, Jobs |

Until 2026-08-19 there was only the first, so prior-art search covered conversations and missed
decisions entirely. **Never edit `memory/vault/`** — edit `/opt/proj/jaredrhod/vaults/brain` and
let the next sync carry it; the mirror overwrites and prunes its own directory on every run.

Two invariants in `mirror_vault.py` carry more weight than the copying:

- **The prune cannot escape `memory/vault/`.** Orphans are deleted so a note removed from the
  vault leaves the index too, and a destination resolved one level too high would delete all
  ~2,250 transcript docs — re-exportable, except for the dream-synthesis notes `dream.sh` copies
  in and `premortem-audit.md`, which are not. `_resolve_dest` asserts the target is a strict
  subpath of `memory/` named exactly `vault` before any unlink, and only `*.md` the mirror wrote
  is removed. `tests/test_mirror_vault.py` pins the way this actually goes wrong: `VAULT_ROOT`
  pointed at an empty directory makes *every* destination file read as an orphan via the normal,
  non-error path.
- **Folder exclusions fail closed.** `11 - Personal` (health, key people, beliefs — which the
  vault's own rules keep out of every boot-loaded file) and `12 - Archive` (a plaintext
  credential) are excluded by *normalized* folder name, so renumbering cannot silently disable an
  exclusion. An unrecognised top-level folder is **also** excluded and reported with a non-zero
  exit, because a plain denylist fails open on the next folder somebody adds. A new vault folder
  therefore breaks the nightly sync loudly until it is classified in `INCLUDED_TOP_LEVEL` or
  `EXCLUDED_TOP_LEVEL`; that is the intended behaviour, not a bug.

A missing vault (every non-Linux host, any fresh clone) is a clean no-op exit 0, and the call
site captures the mirror's return code rather than letting `set -e` abort — a mirror failure must
not keep the transcripts that just exported out of the index.

**Prerequisite:** the py3.12 `.venv-memweave` must exist (memweave requires ≥3.12; it can't live
in the 3.11 project venv). A missing venv makes `sync_memory.sh` exit 1 with a logged error —
`install.sh` registers the cron but does **not** yet build this venv, so a fresh provision needs
it created by hand until venv bootstrap is folded in (Phase 3/4).

**Follow-up (open):** no freshness alarm yet — failures land in the log but aren't alerted, and a
hung export holds the flock so later runs cleanly skip while the store ages. Add a memweave
freshness probe to `healthcheck.sh` (assert index mtime < 48h).

## retrieval index freshness

`CLAUDE.md` routes code reads to jcodemunch and doc reads to jdocmunch before any
`Read`/`Grep` fallback. A stale index therefore doesn't fail loudly — it answers from
outdated content, which is harder to notice than an error. Both indexes are refreshed on
cron and gated in `healthcheck.sh`:

| Index | Refresh | Gate | Failure key |
|-------|---------|------|-------------|
| jcodemunch (`~/.code-index`) | `uncle-j-jcodemunch-reindex` 01:00 + `jcodemunch-watch.service` | `state/jcodemunch-last-indexed.sha` vs git HEAD | `jcodemunch-index-stale` |
| jdocmunch (`~/.doc-index`) | `uncle-j-jdocmunch-reindex` 01:30 + `post-merge-hook.sh` (this repo only, on `*.md` change) | per-repo manifest `head_sha` vs source root HEAD | `jdocmunch-index-stale` |

`scripts/jdocmunch-reindex.sh` differs from its jcodemunch counterpart because jdocmunch
indexes many source roots (9 currently), most outside this repo. It enumerates
`~/.doc-index/local/<name>.json` manifests instead of taking a path, and reindexes only
what drifted — git roots by HEAD-vs-`head_sha`, non-git roots by newest file mtime vs
`indexed_at` — so steady-state nightly cost is near zero. It is `flock`-guarded, skips
repos whose jdocmunch `.json.lock` is held, skips (rather than aborts on) a vanished
source root, and exits 2 if the manifest `index_version` is not the version it knows how
to read.

The doc gate hard-fails only on this repo's own index; the other eight warn without
failing the run.

**Historical note (2026-07-18):** the jdocmunch check previously ran
`ls ~/.doc-index | wc -l` and reported "N repo(s)". That directory holds exactly two
entries (`local/` and `_savings.json`) regardless of index contents, so it reported a
steady `OK 2 repo(s)` and would have done so with the index completely empty. It never
read a date. A check that cannot fail is worse than no check — it converts an unknown
into false confidence, and in this case a false OK was read as evidence and propagated
into a wrong diagnosis. Prefer gates that assert a property over gates that count things.

**What already existed:** `scripts/post-merge-hook.sh` re-indexes jdocmunch whenever a
merge touches `*.md`. It is narrow — `--path "$PROJ_ROOT"`, so it covers this repo and
none of the other eight, and it only fires on merge, not on edit or on external-repo
churn. That is why the Refinery's own index tracked HEAD while the rest drifted for
weeks, and why the gap read as "no automation at all" on first inspection. The cron
generalises it; the hook is not redundant with it.

**Follow-up (open):** `jdocmunch-mcp hook-posttooluse` ships an auto-reindex hook (the
doc-side equivalent of the jCodemunch PostToolUse reindex above) and is not wired up.
It would close the remaining in-session gap for edits that never reach a merge.

## What each component buys you

### prior-art-check

Answers the question "does the agent ask itself 'have we solved this
before' before working?" with **yes, now it does**. Without this skill,
memweave is a CLI the agent *could* run but usually won't. With it,
the agent checks prior work on every non-trivial prompt via `mw_search.py`.
Zero cost on an empty store; 1-2 second overhead on a warm one.

Step 3b (staleness filter): any memweave hit containing `pending`,
`awaiting`, `needs`, `consider`, `not yet`, `TODO`, or `FIXME` must be
verified against current source before being reported as fact. Prevents
the failure mode where a memory entry says "PR awaiting review" long after
the PR has merged and the fix is running. Complements the healthcheck
staleness advisory scan which surfaces the same entries at session start
(warning-only, not a failure).

### judge

Always fires before any non-trivial Edit or Write. Two responsibilities:

1. **Gather structural evidence** — `get_blast_radius`, `get_changed_symbols`, `get_untested_symbols`, `get_pr_risk_profile` from jCodemunch
2. **Delegate to specialist agents** based on that evidence (see trigger matrix below)

Catches the four classic hallucination patterns:

1. Invented functions (call `foo.bar()` where `bar` doesn't exist)
2. Invented imports (import a module that isn't a dep)
3. Wrong signature (skip required parameter)
4. Missed callers (rename symbol, forget to update all sites)

**Skip conditions:** typos, whitespace/formatting-only, comment-only edits, single-variable renames with no logic change, changes already reviewed in the same turn.

### Specialist agent trigger matrix

Six agents in `global-agents/`, symlinked to `~/.claude/agents/`. The judge delegates based on change type. Multiple agents can fire on the same change.

| Agent | Spawn when | Skip when |
| ----- | ---------- | --------- |
| `code-reviewer` | Edit/Write changes function logic, adds/removes functions or classes, modifies control flow, touches API or data model | Typos, whitespace/formatting, comment-only, single-variable rename with no logic change |
| `security-reviewer` | Edit/Write touches user input handling, auth/session/token code, API endpoints, file I/O with user-controlled paths, DB queries, crypto/hashing, payment flows, subprocess/shell execution | Pure UI layout, documentation, config that doesn't touch auth, input, or data paths |
| `silent-failure-hunter` | Edit/Write touches exception/error handlers, async functions, network calls, file I/O, DB operations, subprocess execution, or code using try/except / .catch() / \|\| true / default fallbacks; any new function interacting with an external system | Pure logic, data transformation, UI code with no I/O or error-handling paths |
| `planner` | Spawned BEFORE code when a request spans multiple files, introduces a new feature, or requires phased delivery ("add X feature", "implement Y", "refactor Z across the codebase") | Single-function bug fixes, small contained patches, requests where implementation path is already clear |
| `architect` | Structural decisions — new module/service boundaries, data model design, technology choices, scalability trade-offs, any cross-service or cross-module design question | Routine feature implementation where structure is already established |
| `tdd-guide` | Spawned BEFORE implementation of any new function, class, or module; bug fixes requiring new test coverage; refactors that change observable behavior | Editing existing passing tests, fixing comments/docs, formatting-only changes with no behavior change |

### Ralph harness (our version vs. the plugin)

Anthropic's Ralph plugin (`/ralph`) is the standard Huntley pattern:
loop the agent on a prompt file until it says done.

Our harness (`ralph-harness.sh`) adds structural done-gates:

- `get_changed_symbols` — confirms something actually moved
- `get_untested_symbols(changed_only=true)` — blocks if new code has
  no tests
- `get_pr_risk_profile` — blocks if composite risk exceeds threshold

So the loop only exits when BOTH the model says "done" AND the stack's
structural view agrees. Solves the classic Ralph failure mode where
the model confidently declares victory on a broken change.

Pick the plugin for exploratory runs; pick the harness for anything
you plan to commit.

### Outcomes grader

The `outcomes` skill runs in a **fresh context window** — it has not seen
the working agent's accumulated reasoning. This is the point: a long thread
develops blind spots; a fresh context catches them.

Invoked automatically when `ralph-harness.sh --rubric <path>` is used.
After each iteration:

1. Reads the rubric file (criteria with pass/fail conditions and weights)
2. Evaluates each criterion against the PRD Progress section and repo state
3. Returns a JSON verdict: `pass` or `fail` with specific remediation steps
4. If `fail`, injects the gap report as context for the next iteration

Loop exits only when BOTH the structural done-gate (risk + untested) AND
the rubric grader agree the work is complete. Cap: `OUTCOMES_MAX_ITERATIONS`
(default 5). Set in `~/.claude/settings.json`'s `env` block — written
automatically by `install-reliability.sh` on fresh installs. Override per
run with `export OUTCOMES_MAX_ITERATIONS=N` before calling the harness.

The rubric format lives at `global-skills/outcomes/RUBRIC.md.template`.
Project rubrics go at `.claude/outcomes/rubric.md` within the project repo.

### Superpowers

The single biggest agent-reliability upgrade available in 2026.
20+ skills enforcing real-engineering discipline:

- `brainstorming` — forces requirements clarification before code
- `systematic-debugging` — 4-phase root-cause process, no speculative
  fixes until evidence is gathered
- `test-driven-development` — RED-GREEN-REFACTOR on new code
- `verification-before-completion` — agent must prove the fix works
  before claiming success
- `requesting-code-review` — well-composed hand-off to reviewer
  subagents (pairs with our judge skill)

Caveat from the Claude Code community: total active skill count matters
for context budget. Best practice is 20-25 active skills max; more than
that causes skill-selection bias. Superpowers adds 20+ on its own, so
after installing it, remove skills you don't actually use.

### dwarvesf/claude-guardrails

Security layer, hooks-based:

- **UserPromptSubmit secret scanner** — before your prompt reaches the
  model, scans it for live AWS keys, GitHub/Anthropic/OpenAI tokens,
  PEM blocks, BIP39 phrases. Blocks and warns. Prevents both model
  exposure and session-log leakage.
- **PostToolUse injection scanner** — scans Read / WebFetch / Bash
  output for known prompt-injection patterns. Warns (doesn't block)
  so legitimate security content still works.

Based on Trail of Bits + Lasso research + Anthropic's official security
docs. Low overhead. Worth keeping on always.

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

(memweave memory operational details — freshness, store layout, recovery — are in the "memweave memory freshness" section above. mempalace was decommissioned 2026-06-13; with it gone, the `chromadb==1.5.8` HNSW-corruption-workaround pin + `chroma-hnswlib` dep were also removed from `pyproject.toml` — chromadb was a mempalace-only transitive dependency.)

### Guards that fail *open* (found during the 2026-07-30 Windows port)

A reliability layer is only as good as its failure direction. Five scripts used
this shape:

```bash
exec 9>"$LOCK"
flock -n 9 || { log "Already running — skipping."; exit 0; }
```

MSYS/Git Bash ships no `flock`. The missing binary returns non-zero, which is
indistinguishable from "lock held", so **every run took the skip branch and
exited 0** — and callers reported success. `jcodemunch-reindex.sh` logged
`reindex: OK` while indexing nothing; `telegram-gateway-poll.sh` exited on every
invocation, so the gateway never polled at all. Nothing looked broken.

All five now use an atomic `mkdir` lock directory with an `EXIT` trap, which needs
no external binary and behaves identically on Linux:

```bash
if ! mkdir "$LOCK.d" 2>/dev/null; then log "Already running — skipping."; exit 0; fi
trap 'rmdir "$LOCK.d" 2>/dev/null || true' EXIT
```

**Generalisable rule:** a guard that conflates "the tool is missing" with "the
condition is satisfied" will silently disable the work it guards. When a check
short-circuits to success, verify the check itself ran. Two other latent bugs
surfaced the same way and were *not* Windows-specific — the PostToolUse checkpoint
hook compared `git rev-parse --show-toplevel` to a hardcoded path and so never
fired on any platform, and `healthcheck.sh` asserted an exact SQLite version so a
*newer, safer* SQLite failed the check.

Platform specifics: `docs/WINDOWS-PORT.md`.

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

Note that `surface-write-guard.sh` lives under `~/.claude/hooks/pre-mortem-guard/` as a
real file rather than a symlink into this repo, so it is not covered by `install.sh` or
`refinery-doctor --fix` and cannot be repaired through version control.

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

## A standing red check is worse than no check

`Skill frontmatter regression` failed on every PR for long enough that ROADMAP recorded
its cause as "not readable without a token". While it stayed red, CI provided **zero**
signal: a genuine regression on any later PR would have rendered identically to the
standing failure, and the honest review question — "is this PR's CI clean?" — had no
answer. It was one skill declaring a category absent from `VALID_CATEGORIES`.

The reliability property is not "CI passes". It is **CI's output distinguishes good from
bad**. A check that is always red has the same information content as a check that is
always green.

Practical rules:

- **Fix or delete a persistently failing check.** Leaving it red while merging around it
  trains everyone, human and agent, to merge past red.
- **When merging with a red check, prove it is unrelated rather than assuming it.** The
  cheap proof is running the same test against the base commit in a detached worktree —
  identical failures there means pre-existing. Record that you did.
- **"Fails for a reason not readable" is a finding, not a status.** The job log is
  reachable via `gh api repos/<owner>/<repo>/actions/jobs/<id>/logs`; note that
  `gh run view --log-failed` returned empty here while the API returned the assertion.

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
# Inside claude: /plugin uninstall ralph-wiggum
```


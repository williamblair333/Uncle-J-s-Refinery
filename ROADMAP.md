# ROADMAP — Uncle J's Refinery

Living roadmap. Updated at each session end when items complete or new ones surface.
Completed items age out after ~4 weeks.

---

## In Progress

- _(nothing in flight)_

## Planned

- **[READY TO FILE — needs Bill's sign-off, do not open unattended] Upstream: `get_watch_status`
  reports `any_stale: false` without measuring anything** (`jgravelle/jcodemunch-mcp`, verified
  against installed 1.108.288). Staleness is read from `get_reindex_status`, which is **in-process,
  in-memory** state (`tools/get_watch_status.py:73,90`). The watcher runs in the systemd daemon —
  a different PID — so a querying MCP server has no reindex state, `has_any_reindex_state()` is
  False, and every repo takes the hardcoded `{"index_stale": False}` default. `any_stale` then
  answers False having measured nothing, on the normal path rather than an edge case.
  Reproduced 2026-08-21: all 18 repos `index_stale=false` **and** `watched_by_another_process=true`
  (holder pid 1794), including `/opt/proj/Uncle-J-s-Refinery` whose index was behind its tree at
  the time. Upstream already has the fix in a sibling module: `FreshnessProbe.repo_freshness`
  (`retrieval/freshness.py:245`) returns `fresh`/`stale`/`unknown`/`not_tracked`, and its docstring
  describes precisely this — *"a Boolean has nowhere to put 'I could not find out' … the verdict
  then rendered False as `fresh`."* `get_watch_status` is the caller still using the Boolean that
  tri-state was written to replace. **Routing already corrected in CLAUDE.md §1.**
  This resolves the prior "one narrow scan, not an answer" entry: the tri-state exists, the parked
  note attached it to the wrong tool, and the repo-wide re-scan (110 files) found where it lives.
- **`tests/test_skills.py` reads `SKILL.md` without `encoding=`** — same cp1252
  defect fixed in the memweave scripts, 77 local failures on Windows. (The
  `Skill frontmatter regression` half of this item is **done** — PR #107 recategorised
  `occams-razor`; CI has carried signal since, and ran 8/8 green on 2026-08-14.)
- **`state/hook-blocks.log` has no rotation** — 492K and unbroken since 2026-05-25.
  The weekly review has to scan the whole file to find one session's entries. Needs a
  rotation policy that does not break the review (the log is gitignored session history
  and is NOT reconstructible, so rotation must archive rather than truncate).
- **Close `surface-write-guard.sh`'s detection gaps** (measured 2026-08-15, pinned as
  strict xfails in `tests/test_surface_write_guard.py`). Versioning the guard made these
  reachable; they are **pre-existing** and were verified to behave identically in the live
  installed copy, so they are not regressions. Two root causes:
  - `REDIR_RE`'s `SURF_EXT` and `SURF_FILE` branches both end in a **required** trailing
    delimiter `[[:space:];|&$"']`. At end-of-command there is no trailing character, so
    `echo x >> setup.sh`, `echo '{}' > settings.json` and `echo hi > CLAUDE.md` are all
    allowed — while the same redirect followed by `&& echo done` is blocked.
  - `SED_RE` / `PERL_RE` permit only `[[:space:]a-zA-Z0-9='"]` between the flag and the
    filename; neither `/` nor `.` is in that class. **`SED_RE` fires only on
    `sed -i "" file.sh`** (the macOS empty-suffix form) — `sed -i 's/a/b/' f.sh`,
    `sed -i.bak … f.yml` and `sed -i -e … f.sh`, i.e. essentially all GNU sed usage,
    pass straight through.

    Closing these **widens** a security control, so it needs its own change and its own
    adversarial pass: the failure mode of a careless fix is a false positive that blocks
    legitimate work, and of a sloppy one a false negative, which is worse. Deliberately not
    bundled with the logging fix.
- **Resolve symlinks in `grep-guard.sh::in_repo()`** — it is a literal string-prefix
  test, so repo source reachable through a home-dir symlink
  (`~/.claude/hooks/discipline/grep-guard.sh` → this repo) is allowed by *either*
  spelling. Pre-existing and unchanged by PR #106. Closing it needs `realpath` plus its
  own test pass, since it newly denies reads that work today.
- **push-guard has no notion of *which* command is running.** It matches raw command
  text, so a `git commit` whose message quotes a subshell-wrapped push is blocked as
  though it were the push — hit while committing the push-guard fix itself. Present in
  both the upstream and fixed versions. Closing it needs quote/word awareness, which is
  a real change to a security control: a sloppy attempt risks a false **negative**,
  strictly worse than the false positive. Workaround today: `git commit -F -`.
- **Track upstream issue [dwarvesf/claude-guardrails#17](https://github.com/dwarvesf/claude-guardrails/issues/17)**
  (filed 2026-08-15). Until it lands, **re-running `install-guardrails.sh` re-merges the
  buggy template and restores the bug** over `hooks/discipline/push-guard.sh`. If they
  accept the direction, offer the PR — the tokenised implementation and its 41-case
  matrix already exist here.
- **Fast-forward the second clone off `f3a7ed9`.** Its `main` is still pinned there, and
  the ruleset now *rejects* its push rather than letting it destroy `main`. Until someone
  fixes it, expect a confusing push failure on that machine — that failure is the control
  working. Needs access to the other box.
- **[DONE 2026-08-21] Ground-truth the jdocmunch v1.126.0 confidence rescale.** Verified against
  installed 1.133.0 (`retrieval/confidence.py:1-45`, `retrieval/verdict.py:37`), and the finding
  contradicts what we had written. The scale was **always 0–1** — nothing was renumbered. The bug
  was `strength` reading a raw score against a hardcoded BM25 curve in every mode, so identical
  ranking quality scored 0.62 lexical / 0.087 hybrid. **BM25 thresholds are byte-identical to
  v1.125.0** (`BM25_CEILING = 12.0` makes `1-exp(-3t/12)` ≡ `1-exp(-t/4)`); only hybrid/semantic
  moved, upward, having been understated. CLAUDE.md §3 said the opposite — that any old threshold
  was wrong and the scale unverified — and is corrected. Same mechanism confirmed in jcodemunch
  1.108.288 (`retrieval/confidence.py:51,110`); §1 corrected to match.
  Route that worked: `index_dependency` against the **import** name (`jdatamunch_mcp`), not the
  distribution name — the `top_level: missing` error is specific to passing `jdatamunch-mcp`.
  jdocmunch was already indexed as a watched dep at `~/.code-index/deps/jdocmunch-mcp@1.133.0`;
  `resolve_repo` on that path returns the handle. The `gh api` route below stays valid but is no
  longer needed for this.
  **The rest of the range was verified the same day** — v1.124.1/#104 (ignored args degrade the
  absence verdict), v1.126.1 (dot-dir rule, narrower than we had written), v1.130.0
  (`corpus_selection_changed`) and v1.132.0 (embedding worker on by default, fail-preserving). All
  four are in CLAUDE.md §3 with source lines. The `9235e22` parked note is fully discharged.
- **The `gh api` route for verifying an installed package against upstream** — fetch via
  `gh api repos/<owner>/<repo>/contents/<path>?ref=<sha> -H "Accept: application/vnd.github.raw"`
  then `diff` against the installed copy. Better than reading `.venv/` when the question is
  whether the *local install* has drifted from upstream, rather than what the installed code does.
- **Consider dropping the Python-API call for the plain CLI in `run_index_local()`.** The
  reason it exists — "the CLI exposes no way to pass ignore patterns" — stopped being true
  when upstream #108 added `--extra-ignore-pattern`, `--no-ai-summaries` and `--embeddings`.
  The CLI is already the fallback and already carries all three. The API still buys
  structured JSON in one call, so this is a simplification, not a fix; weigh it on its own.
- **Still worth reporting:** `index_local` crashes with `KeyError 'owner'` when given a name
  colliding with its own sidecar namespace (e.g. `X.summary`) — found 2026-08-08, and
  **not** among the 92 issues on the upstream tracker as of 2026-08-16.
- **[FILED 2026-08-16 — [jdocmunch-mcp#120](https://github.com/jgravelle/jdocmunch-mcp/issues/120)]**
  jdocmunch's watcher flag gap (`jgravelle/jdocmunch-mcp`,
  `service_installer.py`) — found 2026-08-15. `watch-install` accepts no arguments and
  `_exec_cmd()` hardcodes `[sys.executable, "-m", "jdocmunch_mcp", "watch"]`, while
  `_install_systemd()` rewrites the unit with `write_text()` on every run. There is therefore
  no supported way to pin the watcher's indexing posture, and a hand-edited `ExecStart` is
  silently reverted by the next `watch-install` — which the stack-upgrade routine performs.
  Our workaround is a systemd drop-in under `jdocmunch-watch.service.d/`, which
  `_install_systemd()` does not touch. Retire it only after `systemctl --user show
  jdocmunch-watch.service -p ExecStart` shows the flag coming from the unit itself — not on
  the strength of an upstream release note, which would silently restore
  `use_ai_summaries=True`. Ask for `--no-ai-summaries` / `--embeddings` passthrough on
  `watch-install`. The same
  The embeddings half was deliberately **left out** of the filing, per upstream
  CONTRIBUTING's "one issue, one verdict" — and because the version of it recorded here was
  wrong. `watch` does expose no embeddings flag, but the claim that setting
  `JDOCMUNCH_OPENAI_COMPAT_URL` alone turns `use_embeddings="auto"` ON is **false**:
  `openai-compatible` is not in `_EMBED_AUTO_DETECT_ORDER` and is never auto-selected.
  Corrected in SECURITY.md with the evidence. If the narrower version is worth tracking,
  it needs its own issue.
- **The drop-in is still not covered by `install.sh` / `refinery-doctor --fix`.** Detection
  landed (`check_jdocmunch_watch_posture`, below in Completed), so its absence is now *caught*
  — but nothing *restores* it, so a machine rebuild produces a red healthcheck that a human
  must fix by hand. Provisioning the drop-in belongs in `install-reliability.sh` alongside the
  hook symlinks.
- **Extend `refinery-doctor.sh check_jcodemunch_scope` to all five stack servers**
  (jdatamunch, jdocmunch, serena, duckdb) — a reappearing local/project scope is
  currently caught for jcodemunch only. Companion: consider `scripts/win/hook.sh
  autofix` re-asserting the `.mcp.json` copy on Windows (PR #105 follow-ups).

## Recently completed (2026-08-16 — the workaround outlived the bug)

- **Prune-compensation shim deleted** (PR #123). Upstream #102 fixed the `lstrip("./")` bug
  on 2026-08-07; we kept compensating for it for nine days because nobody read the tracker.
  Confirmed fixed by re-running the issue's own repro against our pinned version — both the
  gitignore path and the `SKIP_PATTERNS` path prune correctly with no compensating patterns.
  Only the dead block went: the `forced_ignore` loop that keeps credential-bearing files out
  of the corpus and the raw mirror is untouched, and was re-verified by a live reindex.
- **Upstream [#120](https://github.com/jgravelle/jdocmunch-mcp/issues/120) filed** for the
  `watch-install` flag gap, and a **false embeddings claim in our own SECURITY.md corrected**
  (PR #122) — `openai-compatible` is never auto-selected, and upstream's opt-in gate predated
  our claim by six days.

## Recently completed (2026-08-15 — controls that existed but nothing verified)

- **`surface-write-guard.sh` versioned + its logging fixed** (PR #120). It was never silent:
  `head -c 200` truncates bytes not lines, so one multi-line block wrote four physical lines
  with `session=` stranded on the last. 401 of 3832 lines are continuation junk. Also closed a
  worse defect found while porting — a missing `jq` made the guard `exit 0`, silently allowing
  every command it screens.
- **Two probes for controls nothing was checking** (PR #121). `check_jdocmunch_watch_posture`
  asserts the watcher's *effective* `ExecStart` carries `--no-ai-summaries` (not that the
  drop-in file exists, so upstream passthrough landing does not turn it red).
  `check_vault_hook_registered` asserts the vault Stop hook is still wired.
- **Vault checkpoint Stop hook** (PR #119) — daily note exists, carries a `## Session N` entry
  from this session, vault tree clean. Date comes from the transcript, not the wall clock, so
  midnight-spanning sessions don't false-fire.
- **The local-only doc-corpora invariant is in SECURITY.md** (PR #118), with all three call
  sites named and the embeddings-egress residual recorded.

## Recently completed (2026-08-14 — `origin/main` force-reset: cause, control, detector)

- **The 12 lost commits are re-landed** (PR #108). `origin/main` and local `main` are
  converged; `3f70ec2`, previously on one disk, is reachable from `origin/main`.
- **The cause was identified, after three sessions of calling it unexplained.** Not three
  occurrences but **five** — `f3a7ed9` pushed on 2026-08-04, 08-07 (×2), 08-09 and
  08-14T11:23Z, the last four minutes before PR #107 merged. Writer: a second clone pinned
  at that commit. Found via `git reflog show origin/main` (`forced-update` at `@{2}`/`@{8}`)
  cross-referenced with GitHub push-event `head_sha`. Every prior fix re-landed content
  without touching the write path that removed it.
- **`main` is protected** by ruleset `protect-main-no-force-push` (id `20854165`):
  `non_fast_forward` + `deletion`, no bypass actors, owner included. The repo previously
  had no protection and zero rulesets.
- **Regression detector added** (PR #109) — `scripts/check-origin-main-regression.sh`,
  run from the SessionStart hook, verifying the outcome the ruleset guarantees. Signal is
  non-fast-forward, **not** "local ahead of remote". 10 tests + their own CI job.
- **Two instruments were shown to lie** across all five wipes: `gh pr list` reports
  force-pushed-away PRs as MERGED, and `git branch -a` listed a remote-tracking ref for a
  branch `ls-remote` shows does not exist. **`ls-remote` is the only authority.**

## Recently completed (2026-08-13 — grep-guard `~` paths + hook-blocks log integrity)

- **`grep-guard.sh` denied `~`-prefixed source outside the repo** (PR #106). The guard
  receives the raw unexpanded command string, so `~/…` never arrives as `/…` and the
  out-of-repo exemption (`== /*`) missed it — the same file was blocked by one spelling
  and allowed by the other. `~` is now expanded to `$HOME` before the containment test,
  matching the recursive branch.
- **Multi-line blocked commands corrupted `state/hook-blocks.log`** (PR #106). `head -c`
  truncates bytes, not lines, so one command wrote N rows and only the last carried
  `session=`. 385 of 3452 lines were continuation junk — the real entry count was 3067.
- **Weekly hook-blocks review completed** for 2026-08-13: 33 entries, 23 ALLOWED / 10
  BLOCKED, 9 of 10 blocks confirmed as the guards working correctly. The tenth is
  permanently undiagnosable because the 120-byte truncation cut away the trigger.

## Recently completed (2026-08-08 — MCP scope shadowing + reindex sidecar)

- **All five stack MCP servers restored on Linux** (PR #105). The Windows port's
  committed project-scope `.mcp.json` (`C:\...` commands) shadowed the user-scope
  registration per server name — the missed second half of the PR #103 damage.
  Unshared: moved to `scripts/win/mcp.json`, `/.mcp.json` gitignored, docs updated.
  One-time Windows follow-up: `cp scripts/win/mcp.json .mcp.json`.
- **Nightly jdocmunch reindex no longer fails on phantom `.summary` repos**
  (PR #104). The 2026-08 jdocmunch writes a `<name>.summary.json` sidecar that the
  drift scanner's `SIDECARS` allowlist predated → `KeyError 'owner'`, exit 1.

## Recently completed (2026-08-04 — stack upgrade applied)

- **Stack upgrade landed**, further than planned: jcodemunch 1.108.235 (not .204),
  jdatamunch 1.29.1, jdocmunch 1.121.1 (not 1.120.0). Ran `uncle-j-auto-maintain` by
  hand — same code path as 03:00 — because `uv sync` cannot run from inside a session
  on this host. Lock and sync moved together; `uv.lock` committed in `05722de`.
- **The `uv` cache-retry guard fired in production for the first time** and recovered:
  stale `pysqlite3` cache entry → cleared 1.1 GiB → retry succeeded.
- **Prune shim confirmed on 1.121.1** — `prune compensation` fired on a forced reindex,
  and `unavailable` has never appeared in the log. Closes the 2026-07-31 open question.
  Caveat: the nightly reindex skips when the repo is at HEAD, so it only got exercised
  because a commit moved HEAD.
- **Breaking-change detection fixed** (`54fc502`) after it missed jcodemunch v1.108.208
  removing `content_hash` from `get_symbol_source` responses, while its only hit in 239
  commits was `unbreaking CI lint`.

## Recently completed (2026-07-30/31 — Windows port + silent-failure closure)

- **The Windows port** (sessions 1–3): Task Scheduler jobs replacing cron, `jq`
  and `uv` on PATH, `serena` + `duckdb` registered, four dead hook guards
  revived, and the nightly jdocmunch reindex unfrozen. `HEALTHCHECK: ok`, and
  the 01:00/01:30 jobs verified running unattended.

## Recently completed (2026-06-29 — jMunch Console integration)

- **jMunch Console integrated (light):** `scripts/jmunch-console.sh` launcher; `check-stack-freshness.sh` now tracks
  jmunch-console clone freshness + shows upgrade hint. Usage: `bash scripts/jmunch-console.sh` → `http://127.0.0.1:8765`.
  Phase 2 wiring (healthcheck entry) deferred until stable over a few sessions.

## Recently completed (2026-06-24 — uv-sync recovery + install.sh memweave-venv gap closed)

- **Recovered a machine from a stray plain `uv sync`** (no `--inexact`): it wiped `.venv`
  site-packages — langfuse, the §2b pysqlite3 swap, and the retired mempalace/chromadb deps.
  Restored langfuse + the swap, built `.venv-memweave` + memory index, registered the
  `uncle-j-memweave-sync` cron, installed the `jcodemunch-watch` unit. `HEALTHCHECK: ok`.
- **`install.sh` §2c — provisions `.venv-memweave`** (PR #83): closes the gap where the
  installer never created the 3.12 memweave venv, so memory sync + the Stop hook died on any
  machine that hadn't built it by hand.
- **Mempalace fully retired:** removed the 6 stale `uncle-j-mempalace-*` crons (their scripts
  were already deleted) + untracked `mempalace.yaml`/`entities.json`. (Repo was already decommissioned.)
- Committed the jcode/jdata/jdoc `uv.lock` bump + rebuilt vendored pysqlite3 wheel.

## Recently completed (2026-06-16 — healthcheck loop fixed + pin-canary direct Python)

- **4 healthcheck bugs fixed:** MCP not-Connected hint no longer triggers install.sh; Langfuse
  checks gate on `LANGFUSE_PUBLIC_KEY` so unconfigured machines skip silently; 3 feature-specific
  crons removed from mandatory EXPECTED array; pin-canary hint restored to interactive `run:` form.
- **`scripts/pin-canary.sh` rewritten:** now calls `capture_canary()` directly via `.venv/bin/python`
  from `jcodemunch_mcp.retrieval.embed_drift` — no `claude` binary, no MCP session required.
  Removed the `CLAUDE_CODE_SESSION` guard and `claude -p` approach entirely.

## Recently completed (2026-06-15/16 — git pull self-healing)

- **PR #77 merged:** `install-reliability.sh` prunes stale `~/.claude/skills/` symlinks on re-run;
  `scripts/post-merge-hook.sh` auto-runs `install-reliability.sh` when `global-skills/` or the
  installer changes. `git pull` is now the one command — no manual re-run needed for skill changes.

## Recently completed (2026-06-14 — cron silent failures + healthcheck runtime probes)

- **3 silent cron failures fixed:** `dream.sh` PATH export (dreaming broken since Jun 10 — cron
  couldn't find `claude`); `state/dreaming.env` unquoted cron schedule (bash parsed `2 * * *` as
  a command on every source); `auto-maintain.sh:294` `${#SKILL_NAMES[@]:-0}` invalid bash
  (bad substitution on every run). Healthcheck added `check_dreaming_runtime` (last-run freshness
  >36h = FAIL, surfaces `!!` log clues) + `check_auto_maintain_runtime` (shell error pattern scan).

## Recently completed (2026-06-14 — follow-up sweep + Telegram incident)

- **Telegram red-team depth findings closed (PR #73):** whole-file injection scan on `promote`
  (frontmatter included), `assert_skill_target_safe` removes the destructive `rmtree`, output
  redaction gains relative-`.env` + spaced-`sk-ant` patterns (+ left-boundary fix on the existing key rule).
- **getUpdates single-consumer — 22-day offset-freeze incident (PR #74):** two cron pollers consumed
  one bot token; made the gateway the sole consumer (approve/skip relayed via
  `state/stack-alerts-callback.json`), + F4 log byte-sanitize, F5 datetime tz-aware, per-poll
  observability line. **Freeze resolved live** by repointing the corrupt offset into the real id range.
- **Drain helper hardened + `--catch-up` (PR #76):** removed the negative-offset footgun (it
  confirmed/ate a live test DM); dry-run is now genuinely read-only; `--catch-up` repoints to the
  oldest unconfirmed id so queued messages are answered, not skipped.
- **healthcheck probes (PR #75):** `jcodemunch-watch` daemon liveness (warn-not-fail under cron) +
  memweave index freshness (<48h).

## Recently completed (2026-06-13/14 — security & retrieval hardening)

- **memweave corpus de-noised (PR #71):** skill invocations inject the skill's full body as a
  user-role turn (`Base directory for this skill:`), which the exporter indexed as searchable
  prose — flooding prior-art search with stale (often superseded) skill copies. `iter_turns` now
  drops these; `export_project` made authoritative (deletes a stale `.md` when a session falls
  below `min_chars` after filtering). Corpus rebuilt from scratch (577 indexed / 7746 chunks);
  transcripts untouched. Also committed the `jdocmunch-mcp` 1.70.2→1.71.0 autofix `uv.lock` bump.
- **Telegram restricted-agent lockdown (PR #68):** red-team found a CRITICAL — the restricted
  (untrusted) agent ran `claude --dangerously-skip-permissions` with no tool restriction, so a
  prompt injection could read `.env`/host files and exfiltrate out-of-band. Fixed via tested
  `build_claude_argv()` (no skip-perms / `--strict-mcp-config` / `--disallowedTools`); `/work`
  agent unchanged.
- **jcode watch daemon + grep-guard hardening (PR #69):** activated the `jcodemunch-watch` user
  service (real-time index freshness across all 9 repos); rewrote `grep-guard.sh` to route ALL
  source-code reads (not just `grep -r`) to jcodemunch via per-segment dispatch.
- **understand-anything plugin enabled in project settings (PR #67).**

## Recently completed (memweave migration — fully closed 2026-06-13)

- **LIVE residue scrub (PR #63):** repointed 18 global skills + feature docs + PORTING.md + flowchart
  + GEMINI.md off mempalace → memweave; deleted dead recall-bench + `CLAUDE.md.merged` + `entities.json`.
- **jmunch stack upgraded to HEAD (PR #64):** jcode 1.108.55 / jdata 1.13.1 / jdoc 1.70.2; cleared
  `stack-not-at-head`. (Restart Claude Code to load the new MCP servers; run
  `post-upgrade-mcp-integration` next session.)
- **Audit-sink repoint (PR #57) + `post-audit-mempalace-capture`→`post-audit-memory-capture` (PR #62)**
  + global `~/.claude/` edits applied at the keyboard. The migration (PRs #45–#64) is complete in-repo
  and in global config; mempalace fully decommissioned.
- *(obsolete — mempalace gone)* ~~Upstream MemPalace PR #1607~~ / ~~turbovecdb parallel eval~~.

**Only genuinely-remaining deferred item:** purge the staged trash dirs (2.4 G + 55 G, irreversible —
Bill's call). See HANDOFF + `project_memweave-migration-done`.

## Planned

**Improvement Program** (spec: `docs/superpowers/specs/2026-06-11-refinery-improvement-program-design.md` — phases in order; principles: deterministic-first, local-canonical):

- **Phase 2 — Accuracy instrumentation → memweave migration** ✅ **DONE 2026-06-13** (see Completed). Backend decision (MemPalace eliminated → memweave) resolved 2026-06-12; memweave built (PRs #45–#48) and the full migration + mempalace decommission shipped (PRs #50–#55).
- **Phase 3 — Local rail** — Ollama endpoint + hardware-detect model select (Qwen3-Coder 30B / Devstral 24B / Qwen3 8B tiers); batch pipelines local-first (mine compression w/ content-hash caching, dream synthesis, guide compression); dreaming now promotes into the memweave store; pattern-importance scoring as pure script
- **Phase 4 — Subtraction & absorption** — signed-off deletions (Bill, 2026-06-11): ~~D1 stale palace copies (55GB)~~ executed 2026-06-11; ~~**D2** ChromaDB repair apparatus~~ **DONE 2026-06-13** (mempalace fully decommissioned, PRs #50–#55); **D3** ralph — only if Phase 2 usage counter confirms idle. Plus: CLAUDE.md de-dup (project stub, ~4k tokens/session); absorption check added to `post-upgrade-mcp-integration` (script-diff Claude Code changelog vs harness-layer manifest)

- **Compressed `jcodemunch_guide` return value** — offline compress `_generate_claude_md_snippet()` output via cheap model (Phase 3 local rail candidate); benchmark 20 representative routing queries before/after; ~4,600–5,100 tokens/session savings at full tier; upstream contribution to jcodemunch

- **ralph-harness env-strip (after 2026-06-15)** — strip `ANTHROPIC_API_KEY` + `ANTHROPIC_AUTH_TOKEN` from subprocess env in `ralph-harness.sh` and Telegram gateway; enables Agent SDK credit billing ($0 actual cost within monthly credit); do NOT apply before June 15

- **Telegram chat history persistence** — skill exists (`telegram-chat-history-persistence`)
  but implementation not yet started; would allow querying past bot conversations

- **Agent harness competitive analysis** — skill exists; full analysis not yet run

- **jdocmunch `.summary` sub-indexes report 0 sections** (surfaced 2026-07-23) — healthcheck
  warns for both `Uncle-J-s-Refinery.summary` and `proj-fog-of-chess.summary`. Non-blocking.
  Determine whether the summary index is genuinely unpopulated or the count is misreported;
  the latter would be the same class of counting bug as the 2026-07-19 `ls | wc -l` fix

- **ECC specialist agents** — 6 agents imported; evaluate and integrate into
  active workflows

- **Expand discipline hook surface list** — after 1 week of `hook-blocks.log` data, review BLOCKED patterns and expand `edit-surface-guard.sh` surface list if coverage gaps appear; narrow if false positives are high

- **Telegram gateway — remaining red-team findings** (from `review/telegram-gateway-redteam.md`, which is gitignored — tracked here so they aren't lost): (a) skill-frontmatter prompt injection — `scan_skill_body` scans body only; (b) destructive `promote` `rmtree` on skill-name collision; (c) output-redaction denylist gaps (spaced/prose keys, relative paths); (d) bot token in curl URL → `/proc` disclosure. The CRITICAL (restricted-agent host access) is already fixed in PR #68.

- **jcodemunch skew probe** — the *alignment* half of this item is **done**, and was already
  done when this entry was last read. Verified 2026-08-21: `~/.claude.json` points
  `jcodemunch.command` at `/opt/proj/Uncle-J-s-Refinery/.venv/bin/jcodemunch-mcp`, the same
  binary the reindex writes with (1.108.287), so writer == reader and the
  `sqlite_future_version` fallback cannot recur from this cause. What remains is only the
  **probe**: a `healthcheck.sh` check comparing the reindex-writer version against the MCP
  server binary, so a future re-skew is caught at session start rather than on the first
  failed query. (Original root-cause 2026-07-06, PR #91 HANDOFF.)

---

## Completed (recent)

| Date | Item |
|------|------|
| 2026-07-30 | **Stack ported to Windows 11 + Git Bash** (uncommitted). All three jMunch servers `√ Connected` via project-scoped `.mcp.json` (their CLIs are *not* uniform — jdatamunch takes no args, jdocmunch has no `--transport`); hooks routed through `scripts/win/hook.sh` because `bash` is off-PATH and direct invocation drops shell redirection; `.venv/bin`→`Scripts` compat symlink self-healed on SessionStart since `uv sync` destroys it. `healthcheck.sh --quick` 21 → 8 fails. **Three latent non-Windows bugs found:** `flock` absence made five lock guards fail *open* (reindex logged `OK` while indexing nothing; Telegram gateway never polled), the checkpoint hook's hardcoded root comparison meant it never fired on any platform, and `check_sqlite_version` asserted an exact version so a newer/safer SQLite failed. `tg_security.py`'s module-scope `import fcntl` had been breaking `pytest` collection for the whole suite (+71 tests). Remaining 8: 7 crons (no `crontab`), `features/` extras, serena/context7/duckdb. See `docs/WINDOWS-PORT.md`. |
| 2026-07-05 | **grep-guard false positives narrowed** (PR #89). Three over-broad patterns fixed from real `hook-blocks.log` entries: hyphenated words (`-MORTEM`, `-opt-proj-…`) matched as `-r` flags → token-anchored flag detection; grep pattern args (`"ytd\.sh"`) matched as file operands → pattern/flag tokens skipped; recursive branch ignored the out-of-repo allowance → path-operand walk. Closes the `~/.uncle-j-memory/` reads item. +13 test regressions (40/40); code-reviewer caught a numeric-pattern MEDIUM pre-merge. |
| 2026-06-13 | **pysqlite3 3.51.3 wheel vendored + "duckdb" healthcheck bug root-caused** (PR #65). The recurring `mcp-servers-down(duckdb)` fail was a checkmark codepoint bug (`✓` U+2713 grep vs `✔` U+2714 output) matching zero servers → headlined `missing[0]`=duckdb; fixed to `[✓✔]`. Vendored the pysqlite3-3.51.3 wheel (`scripts/build-vendored-pysqlite3.sh` → `vendor/wheels/`), marker-conditional pin in `pyproject.toml` (PyPI fallback off-platform), `check_sqlite_version` healthcheck assert. Ends the `uv sync` clobber dance permanently. |
| 2026-06-13 | **memweave migration complete — mempalace decommissioned** (PRs #50–#55). 2b-2 freshness cron + Stop-hook; 3b project CLAUDE.md routing → `mw_search.py`; 4a cross-project corpus (`--all-projects`); 4b decommission (scripts/crons/MCP/probes removed, palace staged not deleted, dreaming + 3 global skills repointed); 4c in-repo residue (dead `check_mempalace`, 6 obsolete repair skills, RELIABILITY scrub); 4d removed mempalace/chromadb deps from pyproject/uv.lock; 4e docs sync (README/STACK/ROADMAP + mcp-clients templates). Memory is now offline cross-project memweave (`~/.uncle-j-memory`). Deferred: global `~/.claude/` edits (harness-denied), control-invariant audit-sink repoint, trash purge. |
| 2026-06-11 | Improvement Program Phase 1 — pay-for-itself audit (PR #38): deterministic collectors + scorecard + judgment. KEEP: jmunch-retrieval (5,300:1 payoff), guardrails (315 blocks), langfuse, telegram. FIX: routing-policy (9k tok/session), mempalace storage (0.32 maint share), reliability, skills (prune), dreaming + ralph (instrument). D1–D3 deletions signed off. |
| 2026-06-06 | `dcup` Docker port registry — SQLite registry, flock mutual exclusion, live-reality preflight, sweeper service, PreToolUse hook; 26 projects registered |
| 2026-06-06 | `adversarial-review` skill + workflow — MAD framework (Paranoid/Archaeologist/Pedant/Cynic), 2 debate rounds, judge synthesis |
| 2026-06-06 | `smart-review` skill — rules floor + shadow classifier + drift audit; replaces manual effort-level selection |
| 2026-06-10 | F-04 closed — `healthcheck.sh` `check_mempalace()` now runs both `PRAGMA quick_check` (B-tree) and FTS5 `integrity-check` (inverted-index data layer) as complementary probes |
| 2026-06-10 | ARCHAEOLOGIST-R2-1 closed — post-upgrade SKILL.md step 8 clears `state/post-upgrade-needed`; `session-start-autofix.sh` section 0 warns if flag exists from a prior session |
| 2026-06-10 | PEDANT-R2-1 closed — `auto-maintain.sh` Telegram notification now includes per-package commit range (e.g., `jcodemunch-mcp (abc1234→def5678)`) |
| 2026-06-10 | jragmunch-cli evaluation — verdict: adopt env-strip billing pattern in ralph + Telegram gateway after 2026-06-15 (Agent SDK credit launch); skip review/sweep/changelog verbs (redundant with existing stack) |
| 2026-06-10 | CI test job for `session-end-check.sh` — `test-session-end-check` job added to `ci.yml`; 10 tests (pre-commit + stop-hook modes), 0 API calls, runs on ubuntu-latest |
| 2026-06-10 | Stop-hook session mining — `.claude/settings.json` Stop hook now routes through `scripts/mempalace-mine-convos.sh`; adds HNSW pre/post guard, flock dedup, `--wing conversations` consistency with cron; eliminates dirty-context window |
| 2026-06-10 | post-upgrade-mcp-integration jdatamunch 1.13.0 / jdocmunch 1.69.1 / mempalace 3.4.0 — 19 new tools routed in both CLAUDE.md files; stale `state/post-upgrade-needed` flag cleared |
| 2026-06-10 | post-upgrade-mcp-integration v1.108.50 — `get_session_stats`, `analyze_perf`, `tune_weights`, `test_summarizer` added to jcodemunch Session & tier config in both CLAUDE.md files |
| 2026-06-10 | MCP-Universe skill regression gate — `tests/test_skills.py` (576 static tests, 0 API calls); CI job 4; 6 malformed SKILL.md files fixed (missing `---`, invalid YAML); PR #36 |
| 2026-06-10 | Skill frontmatter standard — hermes-inspired YAML spec (platforms, category, tags, prerequisites, related_skills) written to `state/skill-frontmatter-standard.md`; pilot migration of pre-mortem, smart-review, session-end-checklist, prior-art-check; PR #35 |
| 2026-06-10 | jOutputMunch adoption — `## Output Token Economy` section added to both CLAUDE.md files; adversarial-review ran (2 HIGH + 6 MEDIUM fixed); SHA-pinned citation, correct null-strip predicate, success:false clause restored; PR #33 |
| 2026-06-10 | F-03 closed — bypass instruction removed from smart-review SKILL.md Step 6 and hook stderr; hook now says "Run /smart-review" |
| 2026-06-10 | F-05 closed — `gh pr *` hook split into `gh pr create *` + `gh pr merge *`; `gh pr list/view/status` no longer blocked |
| 2026-06-10 | CYNIC-R2-4 closed — flock guard + explicit exec error handling in `scripts/jcodemunch-reindex.sh` |
| 2026-06-10 | duckdb healthcheck false-positive fixed — 3s retry for uvx cold-start in `healthcheck.sh` |
| 2026-06-06 | Smart-review auto-invocation gates — PreToolUse hooks block `git push` / `gh pr create` without review clearance marker |
| 2026-06-05 | MemPalace HNSW empty-index root cause fixed — `repair --from-sqlite` leaves 0-byte `link_lists.bin` for small collections (< 50K items); fixed by post-repair force-flush step, writer-check MCP exclusion, healthcheck per-collection sync + 0-byte detection + auto-repair; upstream bug report + PR draft written |
| 2026-06-05 | design memory system — 5 MemPalace entries (pre-mortem invariants, enforcement hook attack vectors, dreaming pipeline, Telegram gateway, HNSW/FTS5+healthcheck); `post-audit-mempalace-capture` skill committed; pre-mortem step 11 + session-end-checklist Step 6b wired |
| 2026-06-05 | pre-mortem skill hardened — 3-cycle red/blue-team; 27 patches; 2 CRITICALs + 7 HIGHs closed; MEDIUM bundle, WarGames cap, fail-closed audit, cross-session memory |
| 2026-06-05 | turbovecdb security PR #2 merged — all findings fixed, 7 new tests, 46/46 passing |
| 2026-06-04 | turbovecdb security review — 1 HIGH + 1 MEDIUM + 2 LOWs found and fixed; PR #2 submitted to kostadis/turbovecdb; 7 new tests; scale test (290K drawers) pending |
| 2026-06-03 | MemPalace community knowledge share — two GitHub Discussions published: journey/war-story post (#1685) + HNSW silent corruption technical reference (#1686); covers Rust binding bug, dict pickle, FTS5 false-ok, SQLite mismatch, nightly cron destroy |
| 2026-06-03 | Dreaming CLAUDE.md injection path closed (palace path + pattern-promotion mitigated, not closed) — URL hold-filter in `dream.sh` quarantines URL-bearing playbooks to `state/dream-pending-review/`; cascade guard preserves CLAUDE.md if all playbooks held; `dream-synthesizer` SKILL.md anti-promotion rule for citation behaviors; Stop-hook citation audit still needed to structurally close pattern-promotion |
| 2026-06-03 | Dict-pickle root cause closed — verified `_persist()` is sole `pickle.dump` in chromadb; dict can't recur via any normal op; Step 2b (dead WAL commit, failed every run) removed from repair script; Step 2c comment corrected |
| 2026-06-03 | MemPalace dict-format pickle detection hardened — `healthcheck.sh` now probes pickle type (BAD:/ERR: discrimination, traceback-safe); `mempalace-repair-now.sh` Step 2c auto-migrates dict→SimpleNamespace after every repair; three code-review bugs fixed |
| 2026-06-03 | SQLite WAL data race bug fixed — upgraded to 3.51.3 via pysqlite3 source build; `.pth` patch covers all venv processes; install.sh step 2b auto-rebuilds on fresh machines; scan-commit.sh lockfile exemption fixed |
| 2026-06-03 | FTS5 corruption root cause eliminated — disabled `fts5-guard.sh` (concurrent B-tree corruptor), fixed `session-start-autofix.sh` to use venv Python + PRAGMA quick_check + flock, fixed healthcheck false-ok (was using FTS5 integrity-check), fixed `install_cron()` prefix matching, deduplicated 6 crontab entries; HEALTHCHECK: ok |
| 2026-05-28 | Review-queue triage workflow — `review-queue-triage` skill in regular session rhythm; `_review/` cleared |
| 2026-05-28 | Telegram multi-agent routing — `/work <msg>` dispatches to project-context Claude (CLAUDE.md loaded); default stays restricted; `config/telegram-agents.toml` config; hardcoded fallback on missing/malformed TOML; PR #20 |
| 2026-05-28 | MemPalace HNSW nightly destruction fixed — three-bug root cause: missing `--skip-if-healthy`, WAL never committed to HNSW, post-repair check SQLite-only; PR #19 |
| 2026-05-27 | `install-reliability.sh` plugin auto-install — superpowers + ralph-wiggum at user scope; `skill-link.sh` Stop hook no longer unlinks global-skills |
| 2026-05-27 | FTS5 guard + repair/mine coordination + skill-link blocking fix; `features/mempalace/install.sh` cron coordination; PR #14 |
| 2026-05-26 | `scripts/refinery-doctor.sh` — config drift detection + repair; 4 checks: embed-model, jcodemunch-scope, claude-md-sync, env-placeholders; atomic `--fix`; PR #13 |
| 2026-05-26 | `skill-link.sh` walks `global-skills/` — all globally promoted skills now auto-symlink on every session open; no manual `install-reliability.sh` needed after `git pull` |
| 2026-05-26 | 5 machine-local skills promoted to global — `pre-mortem`, `healthcheck-interactive-hints`, `mempalace-boot-repair-always-runs`, `platform-removal-cleanup`, `stop-hook-dedup-guard` |
| 2026-05-26 | `pre-mortem` skill restored — adversarial failure analysis (12 dimensions, WarGames escalation) synced from dma64 machine; discipline system fully operational |
| 2026-05-26 | `stack-not-at-head` resolved — jcodemunch-mcp 1.108.20 → 1.108.24; healthcheck path check relaxed to accept code-index venv |
| 2026-05-26 | `SessionStart` git fetch hook — async `git fetch --quiet` wired in `~/.claude/settings.json`; remote tracking state no longer stale at session open |
| 2026-05-26 | `uncle-j-mempalace-repair` cron restored — 4am nightly `mempalace repair` re-added to crontab; was dropped during `@reboot --skip-if-healthy` transition |
| 2026-05-25 | Blocking discipline hooks wired — `edit-surface-guard.sh` (pre-mortem gate on surface-list edits) and `grep-guard.sh` (routes `grep -r` to jcodemunch); `install-reliability.sh` now installs them on fresh machine |
| 2026-05-25 | `@reboot` repair made conditional (`--skip-if-healthy`); repair output now streams live |
| 2026-05-25 | MemPalace dict-format pickle root cause found — migrated `f89df21a` to `PersistentData`; fixed FTS5; fixed `mempalace-health.py` live query; added SessionStart health check hook |
| 2026-05-25 | `session-status-briefing` skill updated — now includes HANDOFF.md read and healthcheck.sh run as mandatory first steps |
| 2026-05-24 | MemPalace self-healing repair — FTS5 auto-rebuild pre-flight added to both `repair --yes` and `repair-hnsw rebuild` paths; 3 regression tests in repair.py, 2 in cli.py; fog-of-chess wing deleted (437K drawers); HNSW rebuilt clean at ~94K |
| 2026-05-24 | `mempalace-repair-verify.sh` — new verification script: SQLite vs HNSW count, FTS5 integrity check, semantic search smoke test |
| 2026-05-24 | `mempalace-delete-wing.py` — new utility: deletes a MemPalace wing by drawer prefix |
| 2026-05-23 | MemPalace HNSW permanent fix — `chroma-hnswlib==0.7.6` pinned in project deps; `CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI` set in all mine/repair/MCP scripts and crontab; health check thresholds corrected; stop hook routes via script |
| 2026-05-23 | MemPalace HNSW corruption root-cause fix — `hnsw:num_threads=1` on all collections neutralizes updatePoint race; health check now detects trillion-element header corruption; `mempalace-repair-now.sh` added |
| 2026-05-23 | Nightly MemPalace repair cron — 4am automated `mempalace repair` prevents HNSW drift; healthcheck detects drift and prompts repair |
| 2026-05-23 | Session-end checklist system — three-layer enforcement (skill → Stop hook → pre-commit block) |
| 2026-05-23 | Standard project docs — LICENSE (AGPL-3.0), CONTRIBUTING.md, SECURITY.md, ROADMAP.md |
| 2026-05-23 | `telegram-inline-button-promote` skill — inline keyboard button wiring pattern documented |
| 2026-05-23 | `session-end-checklist` skill symlinked — invocable as `/session-end-checklist` |
| 2026-05-23 | Telegram backlog age filter — drops messages >10 min old to prevent rate-limit burn |
| 2026-05-23 | `install.sh`: Telegram overwrite protection — `[y/N]` default, skip if not configured |
| 2026-05-23 | `install.sh`: Context7 API key setup — auto-reads `context7.key`, falls back to prompt |
| 2026-05-23 | Context7 API key configured — `~/.claude/.env` populated |
| 2026-05-23 | Git pull — merged 22 upstream commits; ECC agents, healthcheck-notify, new skills |
| 2026-05-22 | Telegram gateway notifications — healthcheck alerts, skill drafts, Ralph/dream FYIs |
| 2026-05-22 | Skill approval flow — auto-maintain drafts skills instead of auto-committing |

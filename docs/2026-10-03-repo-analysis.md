# Repo analysis and recommendations — 2026-10-03

Source: a cloud Claude Code session over `williamblair333/Uncle-J-s-Refinery` at `8b927a6`, run
without the retrieval stack (no jcodemunch/jdocmunch/serena registered in the cloud container),
so findings come from direct file reads and a local pytest run. Host-only state (crons, `~/.claude`,
the vault, local branches) was **not** visible and is cited from `HANDOFF.md` where relevant.

Status legend: **DONE** shipped · **PROPOSED** ready to do, low risk · **DECISION** needs Bill.

---

## 1. Snapshot

| Item | Value |
|---|---|
| Purpose | Installer + operating layer for Claude Code: 6 MCP servers, memweave, guardrail hooks, self-heal crons, nightly dreaming |
| History | 116 commits, 2026-08-04 → 2026-10-01, single maintainer |
| Files | 259 tracked; 117 `.md`, 72 `.sh`, 41 `.py` |
| Skills | 50 in `global-skills/`, all with `SKILL.md` |
| Optional features | 11 under `features/` |
| Tests | 17 files; `947 passed, 3 skipped, 7 xfailed` locally with plain pytest |
| CI | 17 jobs after PR #151, all green |
| Largest docs | `CHANGELOG.md` 350 KB, `HANDOFF.md` 327 KB, `CLAUDE.md` 83 KB |

The skipped tests need the ONNX model or `.venv-memweave`, or the installed live guard. The
xfails are the strict `KNOWN_GAPS` cases in `test_surface_write_guard.py`.

---

## 2. Done this session

- **DONE — CI covers all 17 test files** ([PR #151](https://github.com/williamblair333/Uncle-J-s-Refinery/pull/151), merged as `4e71973`).
  New jobs: `test-grep-guard`, `test-auto-maintain-verdict`, `test-tg-security`, `test-memweave`.
  A duplicate job number "11" was renumbered to 13.
- **DONE — `CONTRIBUTING.md` clone URL** now points at `williamblair333/…` instead of `wblair8689/…`.

---

## 3. Trim `CLAUDE.md` — the main recommendation

### Why

- It is ~20k tokens and is deployed to `~/.claude/CLAUDE.md`, so it loads in **every** project.
- About 100 of its 883 lines are upstream release history: version deltas, "verified against
  X at file:line", and descriptions of bugs that are already fixed. Outside this repo almost none
  of it applies.
- The real cost is attention, not money. The dozen rules that change behaviour are buried under
  narrative. Examples: treat an empty result as `degraded`; handle `safe: None`; re-index after
  id moves.
- It fails the README's own standing test: "every component must pay for itself."

### What it costs in dollars (Opus 5.5 rates)

| Item | Cost |
|---|---|
| Cache write of ~20k tokens, once per session or after 5 idle minutes | ~$0.10 |
| Cache read, per request | ~$0.004 |
| 100-request session | ~$0.50 |

Halving the file saves about $0.25 a session. That's worth having, but it's not the main reason.

### Risks

- **Load-bearing rules hide inside history bullets.** Delete narrative, never the rule; each rule
  survives as one line.
- **It regrows.** `scripts/auto-maintain.sh` (around lines 305–340) tells the nightly agent to
  update `CLAUDE.md` after each upgrade. `scripts/stack-alerts-poll.sh` (around line 71) asks the
  same question. A trim without changing those prompts lasts one upgrade.
- **Deploy contract.** `tests/test_claude_md_deploy.py` requires a deploy to keep the installed
  copy's `dream.sh`-appended "Dreaming Notes" tail. `refinery-doctor.sh` and `install.sh` compare
  and overwrite the deployed copy. The new structure must pass that test unchanged.
- **Moved detail is only seen on demand.** That's fine for history and wrong for rules.

### Plan (PROPOSED)

1. **Split the file.**
   - The lean `CLAUDE.md` targets 150–250 lines. It keeps the modality routing table, the
     operating rules per tool family, the absence contract (`absent` vs `degraded`), the
     memweave invocation, the fallback rules, and the output-economy section.
   - Every live gotcha becomes a one-line rule with no version narrative. For example:
     "`check_rename_safe.safe` may be `None`; treat it as unknown, not safe."
   - Move all version and changelog narrative to a new `docs/JCODEMUNCH-CHANGES.md`. jdocmunch
     indexes it, so it can be found on demand.
2. **Redirect the writers.** Change the auto-maintain and stack-alerts prompts:
   - Upgrade notes go into `docs/JCODEMUNCH-CHANGES.md`.
   - `CLAUDE.md` changes only when a routing rule or a behaviour-changing contract changes.
   - Add a test in `tests/test_auto_maintain_verdict.py` that pins the new prompt wording.
3. **Add a size guard.** Add a CI step that fails when `CLAUDE.md` exceeds 30 KB, so growth gets
   reviewed instead of creeping.
4. **Verify.**
   - Run `uv run pytest tests/test_claude_md_deploy.py` and the full suite.
   - Before and after, compare `get_session_stats` and 3–5 routing tasks: a symbol lookup, an
     absence claim, a CSV question, a memory search. Confirm the tools chosen are unchanged.
   - Run `audit_agent_config` on the new file.
5. **Deploy** with `scripts/refinery-doctor.sh --fix`, then confirm the Dreaming Notes tail
   survived in `~/.claude/CLAUDE.md`.

---

## 4. Model and effort choice

What Anthropic has published, from the "optimizing for cost and intelligence" page, fetched
2026-10-03:

| Benchmark | Model @ effort | Score | $ per solved task |
|---|---|---|---|
| SWE-bench Pro | Opus 5.5 @ low | 87.4% | 0.12 |
| SWE-bench Pro | Opus 5.5 @ medium (default) | 92.8% | ~0.22 |
| SWE-bench Pro | Fable 5.1 @ low | 88.6% | 0.54 |
| SWE-bench Pro | Fable 5.1 @ default | 92.3% | 1.19 |
| SWE-bench Pro | Sonnet 5 @ default | 77.4% | 0.84 |
| DeepResearch Bench II | Fable 5.1 @ low | 66% | 4.66 |
| DeepResearch Bench II | Opus 5 @ default | 71% | 6.71 |
| DeepResearch Bench II | Sonnet 5 @ default | 56% | 1.20 |

Opus 5.5 effort curve on SWE-bench Pro, relative to `high`:

| Effort | Score | Cost |
|---|---|---|
| low | about 8 points lower | about ⅓ |
| medium | about 2.5 points lower | about 70% |
| xhigh | about 1.4 points higher | about 2.5× |

No published numbers exist for Sonnet 5.5 at any effort level.

**Recommendations**

- **Default to Opus 5.5 at `medium`** for Refinery work: repo analysis, CI, scripts, PR driving.
  This session's analysis-and-PR work cost about $4.34 on Fable 5.1 before switching.
- **Use Fable 5.1 only when Opus 5.5 at `high`/`xhigh` still falls short** on long-horizon or
  hard design work. Fable earns its price mainly at `low` effort.
- **Don't assume Sonnet is cheaper per task.** Sonnet 5 had half Opus 5.5's token price and cost
  about 4× more per solved coding task. Consider Sonnet 5.5 for high-volume, checkable, simpler
  routes.
- **PROPOSED:** sweep effort on 5–10 real Refinery tasks before changing the defaults for the
  nightly crons. `dream.sh`, `auto-maintain.sh` and `ralph-cron-run.sh` are the spend that
  repeats. Compare cost per completed task, not per token.

---

## 5. Other findings

| # | Finding | Status | Action |
|---|---|---|---|
| 5.1 | `HANDOFF.md` (327 KB) and `CHANGELOG.md` (350 KB) are append-only. Agents read `HANDOFF.md` at session start, so its size is paid repeatedly. | PROPOSED | Keep `HANDOFF.md` to open items and the latest 2–3 entries. Archive older ones to `docs/handoff-archive/YYYY-MM.md`, which jdocmunch indexes. Leave `CHANGELOG.md` as the record, since it isn't auto-loaded. |
| 5.2 | Per `HANDOFF.md` (2026-09-23), branch `skill-occams-domain-first` is unpushed. It also carries an unrelated `ecc888d chore: post-upgrade sync` commit. | DECISION | Decide whether the commit body's quoted session reasoning can go public. Cherry-pick or drop `ecc888d` before opening a PR. |
| 5.3 | Per `ROADMAP.md`, the nightly agent commits to local `main` and never pushes. | DECISION | Already logged. The 2026-09-30 handoff shows three such commits riding along on an unrelated PR. A push step, or a dedicated branch plus PR, would stop that. |
| 5.4 | `AGENTS.md` and `CLAUDE.md` forbid Read/Grep/Bash for code. In environments without the stack, such as cloud sessions, the rule can't be followed and agents must improvise. | PROPOSED | Add one line: "If the stack's MCP servers aren't registered (`list_repos` unavailable), say so and fall back to Read/Grep." `CLAUDE.md` half-covers this for context7 only. |
| 5.5 | The `PRODUCT.md` verify block covers only the product-quality subsystem. `install.sh` has no clean-machine test. | DECISION | Already in ROADMAP. It needs a stub Claude config plus a cached wheel set. Until then, `healthcheck.sh` on the host is the only full-stack evidence. |
| 5.6 | The memweave ONNX and `mw_search` tests skip in CI because the runner has no model. | PROPOSED | Cache `all-MiniLM-L6-v2` in CI with `actions/cache`, keyed on the model's revision, so the semantic path actually runs. |
| 5.7 | `jscrub` isn't wired into anything (ROADMAP 2026-09-03). | DECISION | Already logged. The low-risk half is the `check-vendor` CI job; it needs no `--in-place`. |
| 5.8 | Commit-message examples in `CONTRIBUTING.md` hardcode an old co-author model name. | PROPOSED | Use a placeholder ("Co-Authored-By: <agent> …") so the doc doesn't go stale on each model release. |

---

## 6. Suggested order

1. §3 `CLAUDE.md` split plus writer redirect. This has the biggest per-session effect.
2. §5.1 trim `HANDOFF.md`. Same mechanism, small diff.
3. §5.4 fallback line, and §5.8 placeholder. Small doc edits.
4. §5.6 cache the ONNX model in CI.
5. §4 effort sweep on the nightly jobs, then pin their models and efforts.
6. The DECISION items (§5.2, §5.3, §5.5, §5.7) when Bill has time.

Each PROPOSED item is one PR. Run the full pytest suite before pushing.

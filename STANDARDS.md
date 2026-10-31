# Standards — Uncle J's Refinery

The bar is set from the seats of a platform/SRE engineer, an LLM-evaluation engineer, a release
engineer and a security engineer. Each would already have these in place for a personal agent
platform that one person runs unattended across three hosts.
**Goal** (PRODUCT.md): agents in any repo get structured retrieval instead of brute-force
reading, and the person supervising them gets work that is checked before it's called done.
That has to hold offline, at low token cost, without Bill having to notice things.
Items are ranked by their impact on that goal, highest first. Written 2026-10-31 with
`expert-bar` + `think-wider`.

## How this bar was widened (think-wider, 2026-10-31)

- **Shape:** one owner runs a fleet of semi-reliable automated workers. Their output has to
  be trusted without the owner watching, and they should raise what's missing before he asks.
- **Aviation FOQA** (routine flight-data monitoring) flags exceedances in normal flights
  before they become incidents. Here: mine every transcript for exceedances on a schedule (meta-questions,
  workarounds, takeovers). Don't wait for Bill to notice.
- **Manufacturing SPC** puts control limits on a rate, and a point outside the limits triggers
  action. Here: `just offload`, `workaround-bench` and `check-bench` print numbers, but nothing
  alerts when one drifts.
- **Financial audit** samples closed transactions at random, and the sampling is done by someone other than the preparer. Here:
  a weekly random sample of "done" claims gets re-checked by a different model.
- **Medicine M&M:** every case ends in a control, not a lesson. This is partly in place already (bench-not-watch).
- **First principles:** Bill's attention is the scarce resource, and it only reaches problems
  through pushes (Telegram) and session-start notices. Anything that needs him to go and look will be missed.
- **Outside view:** DORA's 2019 and 2021 State of DevOps reports put elite teams' change-failure rate in the
  0–15% band. Here, 30 of 154 merges in October (19%) were `fix` PRs. That's a loose proxy, since
  not every fix repairs a recent change, but it points to the gates ranked first below.

```yaml
phase: trustworthy unattended — behaviour measured, regressions caught first
standards:
  - id: full-suite-in-ci
    area: release
    bar: Every push runs the whole pytest suite (`just test`), not only skill frontmatter and shell lint
    why: a release engineer never merges on tests that only ran on the author's machine
    status: partial
    evidence: .github/workflows/ci.yml
  - id: meta-question-rate
    area: evaluation
    bar: Bill's meta-questions ("why didn't you…", "why did I have to ask") are counted per session every week from transcripts, with a trend in the Monday report
    why: it's the outcome metric for anticipation; the expert bar and think-wider have no score without it
    status: open
    evidence: symptom categories prototyped 10-31 in a scratchpad (recall 12/15), not shipped
  - id: behaviour-bench-per-hook
    area: evaluation
    bar: Every hook or skill that changes agent behaviour has a replay bench on real transcripts that reports its fire rate and false hits
    why: an LLM-eval engineer ships no prompt change without a regression set
    status: partial
    evidence: just workaround-bench
  - id: skills-red-green
    area: evaluation
    bar: Every global skill has a recorded baseline (without the skill) and a passing run with it
    why: an untested skill is untested code; most skills here were written without a baseline
    status: open
    evidence: think-wider (10-31) is the first with recorded RED/GREEN; the rest have none
  - id: clean-machine-gate
    area: release
    bar: A clean-container install passes before any PR that touches install, hooks or settings merges
    why: PRODUCT.md promises a 900 s clone-to-working install on a fresh machine
    status: partial
    evidence: just install-gate
  - id: installers-idempotent
    area: release
    bar: Re-running any installer leaves tracked files byte-identical
    why: features/skill-manager/install.sh rewrote .claude/settings.json on 10-31, reordering hooks and dropping the cross-platform guard
    status: open
    evidence: no test re-runs installers and diffs the tree
  - id: rate-control-limits
    area: operations
    bar: Delegation success, hook fire rates and self-check corrections each have a limit that pages Telegram when crossed
    why: a rate nobody is alerted on is a rate nobody reads
    status: open
    evidence: just offload prints numbers; nothing alerts on them
  - id: health-daily
    area: operations
    bar: Servers, indexes and crons are checked daily and failures reach Telegram
    why: Bill shouldn't find a broken retrieval path mid-task
    status: done
    evidence: scripts/healthcheck-notify.sh
  - id: retrieval-recall-bench
    area: evaluation
    bar: Memory and code retrieval have a fixed probe set with a recall@5 number, re-run after every stack upgrade
    why: retrieval is the core job; mempalace's was 0.18 and nobody has measured memweave's
    status: open
    evidence: the only recall bench was mempalace's (M0.5); nothing for memweave or jcodemunch
  - id: host-drift
    area: operations
    bar: Every host (main, pi, tc-vmh-03) reports its Refinery commit, and health warns when one is behind main
    why: Bill syncs the hosts by hand and dislikes it; work on a host that isn't pushed is invisible
    status: open
    evidence: no cross-host check
  - id: deps-locked-and-committed
    area: release
    bar: uv.lock is committed whenever the venv changes; the stack never runs unlocked versions
    why: an upgrade nobody can reproduce can't be rolled back
    status: partial
    evidence: uv.lock
  - id: offline-smoke
    area: operations
    bar: A smoke test with the network off proves search, memory and ask_local still answer
    why: offline-capable is one of Bill's four goals; nothing proves it today
    status: open
    evidence: offline ONNX is the default, but nothing runs it with the network off
  - id: secrets-out-of-tree
    area: security
    bar: No credential is tracked in git, and a scan of tracked files runs in CI
    why: the repo is mirrored to GitHub
    status: partial
    evidence: just audit
  - id: kill-switch-per-feature
    area: operations
    bar: Every hook and cron can be switched off with one documented line, and health reports what's off
    why: a misfiring hook has to be stoppable mid-session without editing settings
    status: partial
    evidence: healthcheck.sh
  - id: docs-match-code
    area: release
    bar: README, SKILLS.md and CLAUDE.md claims are checked against the code by a script, not by memory
    why: four boot-loaded routing claims once said the opposite of the code
    status: partial
    evidence: scripts/gen-skills-reference.py
  - id: incident-to-control
    area: operations
    bar: Every incident in HANDOFF ends in a regression test or a gate, linked from the entry
    why: medicine's M&M rule — an incident is closed by a control, not a lesson
    status: partial
    evidence: tests/test_check_bench.py
  - id: state-rotation
    area: operations
    bar: Every state/*.jsonl and log is rotated or capped
    why: unbounded logs fill the disk on the Pi first
    status: open
    evidence: self-work.jsonl rotates (10-27); no check covers the other state files
ideas:
  - id: foqa-transcript-sweep
    idea: A nightly sweep scores every transcript for exceedances (meta-questions, workarounds, Claude takeovers of delegated jobs) and sends the top three
    from: aviation FOQA
    test: run it over the last 14 days and check the top three against what Bill actually complained about
    kill: fewer than 1 in 3 of the flagged sessions is one Bill would call a problem
    status: untested
  - id: spc-limits
    idea: Treat each weekly rate as a control chart, with a limit at the mean plus 3 sigma over the last 8 weeks
    from: manufacturing SPC
    test: backfill 8 weeks of offload and workaround rates and see whether the limits flag the known bad weeks (10-26 agy failures)
    kill: the limits miss 10-26, or flag more than one normal week in four
    status: untested
  - id: audit-sample
    idea: Each week, five random "done" claims are re-checked by a different model (referee) from the original task alone
    from: financial audit sampling
    test: run it on five PRs merged in October
    kill: none of the five finds anything Bill would act on
    status: untested
  - id: forecast-next-questions
    idea: Before ending a long turn, write the three questions Bill is most likely to ask next, and answer them
    from: first principles (attention is the scarce resource)
    test: score the forecasts against Bill's actual next messages over 10 sessions
    kill: the hit rate is under 1 in 3
    status: untested
```

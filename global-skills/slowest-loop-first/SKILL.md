---
name: slowest-loop-first
description: Use when a fix or change can't be proven until something outside your control happens — a random roll, a live user or event, a nightly or scheduled run, a real device, a staging fleet — or when proving it takes more than a few minutes. Also use when starting work on a project with an inherited rule like "verify on the live system", and when a watch or alert wakes you to fix one more thing in a running system.
version: 1.0.0
platforms: [linux, macos]
category: analysis
tags: [testing, feedback-loop, harness, test-bench, verification, leverage]
---

# Slowest Loop First

## Overview

Time-to-proof bounds every fix in a project. When it runs on luck, a schedule or live traffic,
a harness that makes it minutes beats care on each fix.

## When it fires

Any one of these:
- A fix is "waiting to be proven" on an event you can't trigger (a 25% roll, a vendor sending an
  empty file, a push arriving mid-upgrade, the 02:00 run).
- Time-to-proof for a typical change is more than ~5 minutes.
- Project memory or a team rule names the slow system as the test bed.
- You're about to patch one more thing in a live system after a watch or alert woke you.

## The move, in order

1. **Write the time-to-proof table** for the fixes in flight and the next likely ones:
   `change | how it's proven now | time-to-proof | what it waits on`.
2. **If any row waits on chance, a schedule or live traffic:** stop fixing and build the bench
   before the next fix. A bench is a reusable suite grouped by the system's actions, not a one-off
   workaround for today's stuck fix. Assemble it from what the repo already has: scripted inputs,
   cheats and fixtures, debug flags, local entry points (`--input-dir`), state loaders, mocks.
3. **Prove the bench before trusting it.** Run one smoke case per bench primitive (each spawn,
   teleport, mock or loader you've never used) and see it do the real thing. Until it passes, the
   bench is a fast loop that lies.
4. **Wall the bench off from real state.** Use separate saves, data directories or accounts, so
   it can't overwrite the live system. That has to be structural, not a convention.
5. **Re-rank the inherited rule; don't drop it.** Find out why "verify on live" was written. Keep
   the live system as the final acceptance check. Make the bench the development loop that
   proves each change first. Tell the user about the amendment and get their agreement.
6. **Then go back to the fix,** proven on the bench; live is acceptance only.

**Live incident in progress?** Triage it first, read-only: keep the evidence and stop the damage.
The bench comes before the next *fix*, not before triage.

## Quick reference

| You catch yourself… | Instead |
|---|---|
| Setting a watcher to catch the first real occurrence | Force the occurrence on the bench; keep the watcher for acceptance |
| Calling a forced/synthetic test "interim evidence only" | It's the dev loop; live is acceptance. Different jobs, both count |
| Inventing a workaround for this one fix | Make it a bench case the next fix reuses |
| Using an untried primitive (spawn/teleport/mock) to prove a fix | Smoke-test the primitive first |

## Common mistakes

- **Following the inherited rule as a ban** on faster loops. It describes how acceptance works,
  not the only allowed check.
- **Letting the bench and the real system share state,** such as saves, tables or tokens.

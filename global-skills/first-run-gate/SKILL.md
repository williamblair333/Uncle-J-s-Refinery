---
name: first-run-gate
description: Use before calling any project done, before opening a PR that changes runtime behavior, and when setup or install is suspected broken — "does this still work on a clean machine", "did we break install", "why did the gate block my PR". Also use when a gate report comes back failed or blocked and the failure needs reading.
---

# First-Run Gate

## Overview

Proves a project installs and does its core job on a clean machine, in a
throwaway container, using only its documented steps. **Core principle: a claim
that something works is not evidence. The gate produces the evidence.**

Exit codes never settle it. A tool that catches an error, prints something
reassuring and exits 0 is the specific failure this exists to catch.

## Running it

```sh
python3 $STACK_ROOT/features/product-quality/first_run_gate.py [PROJECT_DIR]
```

Writes `.first-run-gate/report.json` and `report.md`. Exit 0 pass, 1 fail,
2 blocked (could not run — treated as a block, never a pass).

Requires a `PRODUCT.md` with a `verify:` block. If there isn't one, use the
`product-brief` skill first.

```sh
python3 .../first_run_gate.py --check [PROJECT_DIR]   # no container
```

**`--check` is not a pass.** It answers one question — is this brief runnable at
all (parses, has observable expectations, matches the README) — and never runs
the project. A brief whose tool is completely broken still passes `--check`.
Only a full run is evidence.

## What it actually does

1. Pulls the declared image, timing the pull separately so a cold pull is
   visible but not charged to time-to-first-result.
2. Starts a throwaway container; `--network none` when the brief says the
   project needs no network.
3. Copies the project in through a filtered tar — `.git`, `.env*`, keys,
   `node_modules`, `.venv` are excluded. Nothing is mounted, so the container
   cannot write back into the working tree.
4. Runs each documented install step, timing each one.
5. Runs the core task and checks every expectation.
6. Cross-checks install steps against the README — a step that is not in the
   README is docs drift, and fails.

## Reading a result

| Failure | Means | Fix |
|---|---|---|
| `install_failed` | A documented step does not work on a clean machine | Fix the step, or the missing dependency it assumes |
| `docs_drift` | The brief's install steps are not in the README | Make the README match; a stranger reads the README |
| `stdout_contains` / `file` | The core task ran but produced nothing | The real bug. Often a swallowed error with exit 0 |
| `exit_code` | The command failed outright | Read `core_stderr_tail` in the report |
| `blocked` | The gate could not run at all | Not a pass. See below |

`blocked` causes: no `PRODUCT.md`, no `verify:` block, unparseable YAML, no
Docker on this host, expectations that are exit-code only.

## When it blocks a PR

The PR guard blocks only when a `PRODUCT.md` exists, the diff touches something
other than docs and tests, and the report is missing, failed, or from an older
commit. Re-run the gate; a missed time target warns rather than blocks.

Override, recorded in the message, never silent:

```sh
PRODUCT_GATE_OVERRIDE=1 gh pr create ...
```

## Common mistakes

| Mistake | Fix |
|---|---|
| Making the gate pass by weakening `expect:` | That deletes the evidence. Fix the project |
| Using `--help` as the core task | Proves the binary exists, not that the job works |
| Treating `blocked` as "fine, no Docker here" | Blocked is not a pass. Run it where Docker exists |
| Re-running until it passes | Flakiness is a product defect; find the cause |
| Adding credentials so the core task runs | Ship a documented stub mode instead |

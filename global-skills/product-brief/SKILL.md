---
name: product-brief
description: Use when starting a new project, or when an existing project has no PRODUCT.md — before writing code, choosing a stack, or planning features. Also use when the first-run gate reports a missing or unparseable brief, or when a project cannot say in one sentence who it is for.
---

# Product Brief

## Overview

Produces `PRODUCT.md`: what the project is for, who uses it, how a stranger gets
their first result, and a machine-readable block that lets the first-run gate
prove the claim. **Core principle: a brief that a machine cannot check is a wish.**

## Output shape

Write `PRODUCT.md` at the project root with these sections, in this order.
Every one is REQUIRED — an absent section is the failure this skill exists to
prevent, not an editorial choice.

1. **Core job** — one sentence: who, doing what, for what outcome. No feature
   list, no technology.
2. **Users** — who they are, what they already have installed, what they already
   know. This decides how much the first-run path may assume.
3. **Success** — observable measures, including a **time-to-first-result
   target** in seconds: install to first useful output for someone who has never
   seen the project.
4. **First-run path** — numbered commands a stranger can paste, from nothing to
   first result. Every command also appears in the README, verbatim; the gate
   fails on drift between the two.
5. **Non-goals** — what this will not do, so it stops being re-proposed.
6. **UI principles** — how the interface behaves: default output, error shape,
   what it asks for before it does anything. A CLI is an interface; terminal
   output is UI.
7. **`verify:` block** — the machine-readable contract, in a fenced ```yaml
   block (see below).

## The verify block

```yaml
verify:
  image: debian:bookworm-slim   # optional; bare base, no preinstalled toolchain
  network: required             # required | none — declare it, never assume it
  install:                      # verbatim from the README
    - apt-get update && apt-get install -y python3
    - pip install .
  run: mytool process ./sample.txt        # the core job, one command
  expect:
    - stdout_contains: "processed 3 records"
    - file: /tmp/mytool/result.json
    - exit_code: 0              # necessary, never sufficient
  time_target_seconds: 300
```

**`expect` needs at least one observable proof** — a file, or output text. A
tool that catches an error, prints something reassuring and exits 0 passes an
exit-code check while doing nothing, which is the failure the gate exists to
catch. The gate refuses a brief whose expectations are exit-code only.

**The proof must come from the program, not from your test.** Writing
`run: mytool process x; echo done` with `expect: stdout_contains: "done"` passes
while the tool fails — the gate refuses a `run:` that echoes its own expected
string. Assert on text the program prints and files it writes. Prefer `| tee
FILE` over `> FILE; echo ok`, so the real output reaches both stdout and the file
and the exit status stays the program's.

**Credentials:** if the core job cannot run without real secrets, the project
needs a documented stub or offline mode, and `run:` uses it. The gate never
receives credentials. Treat a missing stub mode as a product gap.

**`install_note:`** — when the documented install path cannot run inside the
gate (a `docker compose` project, since Docker cannot nest), state why in
`install_note:` and use the equivalent path. Drift then warns instead of
failing, and the reason is printed in every report. Without the note, using
undocumented steps is a failure, as it should be.

**No `verify:` at all is a legitimate outcome.** A project that needs real
credentials, or a whole stack, and has no stub mode cannot be proven from a
clean machine. Say so in the brief and leave the block out. The gate then reports
`no verify: block`, which is the truth. Do not paper over it with a `--help`
call.

## Quick reference

| Section | The question it answers | Failure if missing |
|---|---|---|
| Core job | Why does this exist? | Features get judged by cost, not purpose |
| Users | What may I assume? | First-run path assumes the author's machine |
| Success | How do we know it worked? | "Done" becomes a matter of opinion |
| First-run path | Can a stranger start? | Setup breaks and nobody notices |
| Non-goals | What are we not doing? | Scope returns every planning round |
| UI principles | What does using it feel like? | Tracebacks and prompts become the interface |
| `verify:` | Can a machine check the claim? | The brief is unenforceable |

## Common mistakes

| Mistake | Fix |
|---|---|
| Core job names a technology ("a Rust daemon that…") | Name the user's outcome; the stack is an implementation detail |
| First-run path starts after install ("run the server") | Start from nothing: clone or install, then first result |
| `run:` is a `--help` or `--version` call | That proves the binary exists, not that the job works. Run the real task |
| `expect:` is only `exit_code: 0` | Add a file or output check; the gate rejects the brief otherwise |
| Success has no time target | Give a number in seconds; slow setup is a real defect |
| Brief written after the code | Write it first; the point is to decide before building |

## After writing it

Run the gate: `python3 $STACK_ROOT/features/product-quality/first_run_gate.py .`

A brief that the gate cannot execute is not finished. Then review the plan
against the brief with `product-focus-review`.

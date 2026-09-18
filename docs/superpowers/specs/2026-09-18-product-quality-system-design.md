# Product Quality System — Design

**Date:** 2026-09-18
**Status:** Approved in chat; spec pending user review
**Owner:** Bill

## Problem

Projects here turn into messes from setup through daily use: install steps that
do not work on a clean machine, first runs that fail, confusing interfaces,
missing recovery paths. Work gets called done without anyone having run it from
scratch.

Baseline testing (3 subagents, 2026-09-17) showed agents already know the
principles — they cut a premature plugin API, added a restore command, and
demoted an architecture-first README without being told to. The gap is not
knowledge. It is that nothing forces the check to happen, and nothing states
what the product is supposed to be before work starts.

## Goals

1. Every project states its core job, users, success measures, first-run path
   and non-goals before code is written.
2. No project is "done" until a clean-machine install plus the core task is
   proven to work by a machine, not by assertion.
3. Any user interface is audited against usability heuristics before release.
4. Existing projects can be retrofitted: audited, ranked, and fixed over time.
5. Enforcement is mechanical (hooks), not a rule someone remembers.

## Non-goals

- Guaranteeing great design. The system raises the floor and surfaces gaps;
  taste and iteration are not automatable.
- Replacing `pre-mortem`, `smart-review`, or `session-end-checklist`. This
  system sits alongside them.
- A metrics/roadmap/PM career toolkit. Out of scope.

## Licensing constraint

Commercial projects are in scope, so CC BY-NC-SA material
(deanpeters/Product-Manager-Skills, Digidai/product-manager-skills) is
excluded — not vendored, not copied, not paraphrased from their text. The
PRODUCT.md template and brief skill are written here from scratch, drawing on
non-copyrightable method names only (Jobs to be Done, MoSCoW, Shape Up
appetite).

`wondelai/skills` `ux-heuristics` is MIT and may be vendored with its LICENSE
and attribution retained.

## Components

### 1. `product-brief` skill → `PRODUCT.md`

New skill in `global-skills/product-brief/`. Produces or updates a project's
`PRODUCT.md`:

| Section | Content |
|---|---|
| Core job | One sentence: who, doing what, for what outcome |
| Users | Who they are, what they already know, what they have installed |
| Success | Observable measures, including a time-to-first-result target |
| First-run path | Install → first result, as numbered commands a stranger can follow |
| Non-goals | Explicitly excluded, so they stop coming back |
| UI principles | Only when the project has an interface |
| `verify:` block | Machine-readable: the core-task command plus the observable proof it worked |

The `verify:` block is what makes the gate runnable rather than aspirational.
Minimal shape:

```yaml
verify:
  image: debian:bookworm-slim      # optional; default below
  network: required                # required | none — declared, not assumed
  install:                         # verbatim from README; drift is a failure
    - apt-get update && apt-get install -y python3
    - pip install .
  run: snapkeep backup ./sample --bucket test
  expect:
    - file: /tmp/snapkeep/manifest.json
    - stdout_contains: "backup complete"
    - exit_code: 0                 # necessary, never sufficient
  time_target_seconds: 600
```

`product-focus-review` (already written) reviews the brief and any feature
request against it.

### 2. `first-run-gate` — the piece that does not exist yet

A skill plus a script, `features/product-quality/first-run-gate.sh`.

Behaviour:

1. Reads `PRODUCT.md` for the first-run path and the time target.
2. Starts a clean container (`docker run --rm`, minimal base image, no
   project checkout mounted, no toolchain for the project's language beyond
   what the README says to install).
3. Executes the README/PRODUCT.md steps verbatim. Any step not in the docs is
   a failure — that is the docs-drift check.
4. Runs the core task from the brief.
5. Asserts observable side effects (files written, HTTP health endpoint,
   process alive, expected stdout content) — **never exit codes alone**. A CLI
   that catches an exception, prints a friendly message and exits 0 is the
   known false-green failure mode.
6. Records per-stage timings so cold image pull is visible but not charged
   against time-to-first-result.
7. Writes `.first-run-gate/report.json` and a short Markdown summary.

Failure modes handled explicitly:

- Docker unavailable → gate reports `skipped: no-runtime`, which is **not** a
  pass; the enforcement hook treats it as a block, overridable only by the user.
- Project needs credentials → brief must declare a documented offline/stub mode;
  absence of one is a finding, not an excuse.
- Network-dependent installs → `network:` is declared in the brief, timings
  separated, failure attributed. An undeclared network dependency that only
  works because the host has connectivity is a finding.
- Secrets → never mounted. A project that cannot demonstrate its core job
  without real credentials must ship a documented stub/offline mode; the gate
  runs that. This is a product requirement, not a testing workaround.
- Host without Docker (e.g. the Windows box) → `skipped: no-runtime`, treated
  as a block, with the same user override as any other block.

### 3. UI audit

Vendor `ux-heuristics` (MIT) into `global-skills/ux-heuristics/` with LICENSE
and attribution. Wire a thin `ui-review` step that runs it against changed UI
surfaces (CLI output included — a CLI is an interface) and records findings with
Nielsen severity 0–4. Severity 3 (major) and 4 (catastrophic) block release.

`frontend-design` (already installed) covers visual design for web UI; not
duplicated here.

### 4. Enforcement

`features/product-quality/install.sh`, following the existing feature pattern
(see `features/skill-manager/install.sh`): symlinks skills, registers hooks in
`~/.claude/settings.json` with markers, and is idempotent. Per the committed
host-absolute-path trap, hooks are registered into the user settings file by the
installer at install time — never committed with absolute paths.

Hooks:

| Hook | Fires | Action |
|---|---|---|
| SessionStart | Session opens in a project dir | Warn if `PRODUCT.md` missing |
| PreToolUse (`gh pr create`) | PR creation | Block unless a first-run-gate pass exists newer than HEAD, and a UI audit if UI files changed |

Hook scope, so the gate stays credible rather than merely loud:

- Docs-only and test-only diffs skip the gate (no runtime surface changed).
- A missed `time_target_seconds` **warns**; it does not block. Only a failed
  install, a failed core task, or a missing expectation blocks.
- A project with no `PRODUCT.md` yet warns on PR rather than blocking, until
  its brief is written; once the file exists, the gate is mandatory. This is
  what makes retrofit possible without freezing every existing repo on day one.

Blocking follows the `pre-mortem` clearance-token pattern already in the repo,
including its rule that only the gate may write its own token.

### 5. Retrofit

`features/product-quality/retrofit.sh`: iterates a list of project paths, runs
the gate and (where a UI exists) the audit, and writes a single ranked punch
list to `docs/PRODUCT-AUDIT.md`:

rank = blocks-first-use > data-loss/recovery-gap > major-usability >
docs-drift > cosmetic.

Read-only. It proposes; it does not fix. Fixes are separate approved work.

## Data flow

```
PRODUCT.md ──► product-focus-review ──► plan ──► build
                                                  │
                                    first-run-gate ├──► report.json ──► PR hook
                                    ui-review ─────┘
```

## Testing

- **Skills** (`product-brief`, `ui-review` wiring): baseline subagents without
  the skill, then with it, per `superpowers:writing-skills`. Record the gaps
  each closed.
- **Gate script:** two fixture projects under
  `features/product-quality/fixtures/` — one that installs and works, one that
  is deliberately broken (undocumented dependency, and a command that exits 0
  after printing an error). The gate must pass the first and fail the second,
  including the false-green case.
- **Installer:** run twice; second run changes nothing.
- **Retrofit:** dry-run against this repo first.

## Build order

1. `first-run-gate` script + fixtures (highest value, nothing else depends on it)
2. `product-brief` skill + `PRODUCT.md` for this repo
3. Vendor `ux-heuristics` + `ui-review` wiring
4. `features/product-quality/install.sh` + hooks
5. `retrofit.sh` + first audit run

## Decisions (were open questions)

**Retrofit scope:** discovery over every git repo under `/opt/proj`, but
**dry-run by default** and opt-out per repo via a `.no-product-gate` marker
file. Discovery finds candidates; the run reports; nothing is enforced on a
repo until its `PRODUCT.md` exists. Rejected "explicit allowlist only" —
a list nobody updates is how projects quietly escape the system.

**Base image:** `debian:bookworm-slim` by default, overridable per project via
`verify.image`. Rationale: minimal, no language toolchain preinstalled, so a
project that silently depends on a host-installed interpreter fails the way it
should. Language-specific images (`python:3.12-slim`, `node:22-slim`) are
allowed when the brief declares the runtime as a documented prerequisite.

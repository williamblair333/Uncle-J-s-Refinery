---
name: post-audit-mempalace-capture
description: After any adversarial/red-team analysis of a component, skill, or control mechanism, write two durable MemPalace entries — design invariants + audit baseline, and closed attack vectors — so future sessions can answer "is this change a regression?" without relying on git history alone.
---

## When to use

After completing any multi-cycle adversarial analysis, security audit, or hardening pass on a component, skill, or enforcement mechanism. Trigger when:
- A red-team/blue-team cycle has closed findings on a component
- A skill or gate mechanism has been formally reviewed and certified
- You want a future session to audit proposed changes against a known-clean baseline

## The pattern

Two MemPalace entries per audited component. No more, no less.

### Entry 1 — Design invariants + audit baseline

Properties that **must hold** in any future version. If a proposed change violates any of these, it is a regression regardless of what the commit message says.

Type: project
Title: [Component] — Design invariants and audit baseline
Body:
  Invariants (numbered — the non-negotiables):
  1. ...
  2. ...

  Audit certification: [N]-cycle adversarial analysis completed [date].
  Final cycle result: [only MEDIUMs/LOWs | no new CRITs or HIGHs].
  Confidence baseline: any single-session edit touching invariants requires its own adversarial pass.

### Entry 2 — Known closed attack vectors

Specific attacks found and patched. A future reviewer scans this and asks: "does this proposed change re-open any of these?"

Type: project
Title: [Component] — Known closed attack vectors
Body:
  - **[Attack name]** — [one-line vector description]; closed by [one-line fix description]
  - ...

## Filter criterion

Only write entries for components where: *"if this changed unexpectedly in 6 weeks, would it matter?"*

Yes → write entries. No → skip.

## What to leave out

- The full component source — that lives in the file
- Every individual patch description — those live in git history and HANDOFF
- Hook or implementation details — those live in the code

## Retrieval contract

With these two entries, a future session asking "is this change safe?" can answer:
- Here are the invariants it must preserve
- Here are the known bypasses it must not re-open
- Here is when it was last certified clean

Without them, git history shows *what* changed but not *whether the change was intentional or a regression*.

---
name: post-audit-mempalace-capture
description: After any adversarial/red-team analysis of a component, skill, or control mechanism, write two durable memory notes — design invariants + audit baseline, and closed attack vectors — into the memweave corpus so future sessions can answer "is this change a regression?" without relying on git history alone.
---

> **Note:** the skill dir name still says `mempalace`; it now writes to the **memweave** corpus
> (`~/.uncle-j-memory/memory/`). The name is retained because its `~/.claude/skills/` symlink
> can't be recreated by the harness — a rename is a Bill-keyboard follow-up.

## When to use

After completing any multi-cycle adversarial analysis, security audit, or hardening pass on a component, skill, or enforcement mechanism. Trigger when:
- A red-team/blue-team cycle has closed findings on a component
- A skill or gate mechanism has been formally reviewed and certified
- You want a future session to audit proposed changes against a known-clean baseline

## The pattern

Two markdown sections per audited component, appended to the memweave corpus. No more, no less.
Both go in one file so they index together and surface as a pair in `mw_search.py`:

Run via the Bash tool (the tool result confirms the write). The heredoc terminator is a unique
token — keep it as-is and do not let baseline content contain that exact line:
```bash
mkdir -p ~/.uncle-j-memory/memory
cat >> ~/.uncle-j-memory/memory/audit-baselines.md <<'PM_AUDIT_BASELINE_EOF'

## [AUDIT BASELINE] <Component> — <YYYY-MM-DD>

### Design invariants + audit baseline
Invariants (numbered — the non-negotiables):
1. ...
2. ...

Audit certification: <N>-cycle adversarial analysis completed <date>.
Final cycle result: <only MEDIUMs/LOWs | no new CRITs or HIGHs>.
Confidence baseline: any single-session edit touching invariants requires its own adversarial pass.

### Known closed attack vectors
- **<Attack name>** — <one-line vector description>; closed by <one-line fix description>
PM_AUDIT_BASELINE_EOF
```

### Section 1 — Design invariants + audit baseline

Properties that **must hold** in any future version. If a proposed change violates any of these, it is a regression regardless of what the commit message says.

### Section 2 — Known closed attack vectors

Specific attacks found and patched. A future reviewer scans this and asks: "does this proposed change re-open any of these?"

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

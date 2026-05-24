# Pre-Mortem Skill — Design Spec

**Date:** 2026-05-23
**Status:** Approved for implementation

---

## Core Philosophy

`verification-before-completion` is backward-looking: "does it work right now?"
`pre-mortem` is forward-looking: "when will it fail, and will we know?"

These are complementary, not redundant. Neither replaces the other.

> Supra-genius isn't knowing more facts. It's asking the right questions before
> reality asks them for you.

The gap this closes: the competence-vs-initiative failure mode where an AI correctly
answers "what if" questions when asked, but never surfaces them proactively. Pre-mortem
makes proactive failure mode analysis a mandatory discipline, not an optional afterthought.

---

## Trigger System

### Definition of Consequential

> Any action whose effects persist beyond this session, cannot be trivially reversed,
> or affects systems that run unattended.

### Surface List (auto-triggers deep analysis)

- Scheduled tasks (cron, systemd timers, @reboot entries)
- Hooks and daemons (stop hooks, start hooks, background processes)
- Persistent file writes (config files, state files, databases)
- Auth / credentials / permissions changes
- Infrastructure (services, ports, network configuration)
- Data mutations (schema changes, migrations, bulk writes)
- Architecture decisions (new modules, service boundaries, data models)
- Third-party integrations (APIs, webhooks, external services)
- Dependency changes (upgrades, downgrades, version pins)
- Deployment actions (push, release, merge to main)

### Minimum Stamp (everything else)

Even non-consequential work gets a two-line confirmation:

```
PRE-MORTEM · [action] · CLEAR — no consequential surfaces detected.
```

Silence stops meaning safety. The user always knows it ran.

---

## Failure Dimension Taxonomy

Twelve dimensions, applied based on surfaces touched. All twelve apply to
infrastructure; a subset to architecture decisions; minimum stamp for
everything else.

| # | Dimension | Key Questions |
|---|-----------|---------------|
| 1 | **Temporal** | Runs on schedule? Machine off? Edge times (midnight, month-end, year-end)? |
| 2 | **Concurrency** | Two instances simultaneously? TOCTOU races? Shared resource contention? |
| 3 | **Environmental** | Disk/memory pressure? Missing env vars? Network down? Permission changes? |
| 4 | **Upgrade Durability** | Survives next package/OS upgrade? Config reset? Future dev accidentally reverts? |
| 5 | **Cascade** | What breaks downstream if this breaks? Hidden assumptions violated? |
| 6 | **Observability** | Errors logged? Alerting in place? Failure diagnosable from logs alone? |
| 7 | **Data Integrity** | Writes atomic? Safe if interrupted mid-write? Rollback path exists? |
| 8 | **Security** | New attack surface? Permissions over-scoped? Sensitive data exposed? |
| 9 | **Scale** | Works at N — what at 10N? Memory leaks over time? Disk accumulation? |
| 10 | **Human Factors** | Will next person understand this? Could someone accidentally undo it? Documented? |
| 11 | **Recovery** | Blast radius? Rollback procedure? Kill switch? Manual override? |
| 12 | **Ecosystem** | Upstream bug worth reporting? Workaround creating debt? Dependency deprecation risk? |

---

## Output Format

```
╔══════════════════════════════════════════════════════════════╗
║  PRE-MORTEM  ·  [action/decision in plain language]          ║
╚══════════════════════════════════════════════════════════════╝

SURFACES DETECTED: [list]
DIMENSIONS CHECKED: [list of applicable dimensions]

[ TEMPORAL ]  ⚠ HIGH
  Adversarial: [direct statement of the failure mode]
  Steelman: [strongest possible case that this WILL fail — not might, WILL.
  Engages with probability, mechanism, and consequence specifically.]
  → Required: [concrete mitigation]

[ CONCURRENCY ]  ✓ CLEAR
  [brief explanation of why this dimension is satisfied]

[ OBSERVABILITY ]  ⚠ MEDIUM
  Adversarial: [failure mode]
  Steelman: [strongest case]
  → Recommended: [mitigation]

SEVERITY SUMMARY:  N HIGH · N MEDIUM · N LOW · N CLEAR
STATUS: ⛔ BLOCKED  /  ⚠ WARNINGS PRESENT  /  ✓ CLEAR TO PROCEED
```

### Adversarial Voice + Steelman

- **Adversarial:** States the failure mode directly. No hedging, no "might."
- **Steelman:** Makes the *strongest possible case* that the failure is real and likely,
  not theoretical. Engages with probability, mechanism, and consequence. The goal is
  honest confrontation, not alarm.
- Steelman applies when there is a genuinely strong case to be made. On clear dimensions,
  a brief explanation suffices.

---

## Escalation Model

### Severity Tiers

**LOW** — flagged in checklist, does not block, logged to MemPalace as advisory.

**MEDIUM** — warns visibly, does not block, logged to MemPalace as advisory.

**HIGH** — blocks. Three-warning WarGames escalation before yielding.

**CATASTROPHIC** — blocks. Same escalation, higher ceremony before transfer.
A risk is CATASTROPHIC when: the action is irreversible AND the blast radius
extends beyond this session (production data deletion, credential revocation,
public infrastructure changes that cannot be rolled back, actions affecting
other users or systems outside this project).

### HIGH Escalation (WarGames Model)

```
Warning 1:
  Adversarial + steelman presented. Work is blocked.

Warning 2 (user persists):
  Restatement, more specific.
  "To be clear: failure mode is [X], condition is [Y], consequence is [Z].
  Still proceeding?"

Warning 3 (user persists):
  Reasoning required.
  "I need your reasoning before I can hand this over."

  User provides "here's why":
    ✓ Engages with steelman → "Acknowledged. Logging. It's on you."
    ✗ Hand-wavy → "That doesn't address [specific steelman point]. Try again."
```

### CATASTROPHIC Ceremony

Same three-warning escalation, plus after valid reasoning:

```
1. "State the action you are choosing to take." (verbatim — not just "proceed")
2. "State what you accept as the consequence."
3. Transfer: "Keys confirmed. Logging. This is on you."
```

The user has the keys. If they choose to turn them with full knowledge, that is
their right. The skill's job is ceremony and documentation, not permanent veto.

### MemPalace Log (every HIGH/CATASTROPHIC transfer)

```
[PRE-MORTEM TRANSFER] YYYY-MM-DD
Action: [verbatim]
Dimension: [which one] — [severity]
Steelman: [full text]
User reasoning: [verbatim]
Reasoning engaged with steelman: yes / no
Responsibility: transferred to user
```

LOW and MEDIUM findings are logged as advisories — no transfer record required.

---

## Integration with Existing Skills

| Skill | Relationship |
|-------|--------------|
| `verification-before-completion` | Complementary. VBC = "works now?" Pre-mortem = "fails when?" Pre-mortem fires before commitment; VBC fires before completion claim. |
| `systematic-debugging` | Debugging finds current root cause. Pre-mortem asks if the fix will hold. |
| `session-end-checklist` | Pre-mortem findings feed into session-end MemPalace snapshot. |
| `prior-art-check` | Runs first (have we solved this?). Pre-mortem runs after action is decided (will the solution hold?). Different timing, different question. |

### Sequence in a Typical Session

```
prior-art-check → [work] → pre-mortem → [address findings]
→ verification-before-completion → session-end-checklist
```

---

## Scope

Fires on: fixes, new features, config changes, migrations, architecture decisions,
third-party integrations, data models, scheduled tasks, deployment actions.

Does not fire on: comment-only changes, whitespace/formatting, pure documentation
edits with no code effect, single-variable renames inside private scope.

Everything not in the surface list gets the minimum stamp.

---

## Success Criteria

- Pre-mortem runs on every consequential action without being asked
- Findings are visible, structured, and specific — not vague warnings
- The adversarial+steelman voice makes real risks undeniable, not easy to dismiss
- HIGH/CATASTROPHIC blocks are respected until resolved or consciously overridden
- MemPalace log creates an auditable record of every accepted risk
- The skill raises questions the user would have had to ask themselves

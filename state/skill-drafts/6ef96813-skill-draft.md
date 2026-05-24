---
name: pre-mortem
description: Use when about to finalize any consequential action — fixes, features, config changes, architecture decisions, deployments, crons, daemons, or third-party integrations. Also triggers when the action affects systems that run unattended, cannot be trivially reversed, or persists beyond this session.
---

# Pre-Mortem: Adversarial Failure Analysis

`verification-before-completion` asks "does it work now?" This skill asks "when will it break, and will we know?"

## Surface List

Fires on these surfaces (auto-triggers deep analysis):

| Surface | Examples |
|---------|---------|
| Scheduled tasks | cron, systemd, @reboot |
| Hooks / daemons | stop hooks, background processes |
| Persistent writes | config, state, databases |
| Auth / permissions | credentials, access control |
| Infrastructure | services, ports, network |
| Data mutations | schema changes, migrations, bulk writes |
| Architecture decisions | new modules, service boundaries, data models |
| Third-party integrations | APIs, webhooks |
| Dependency changes | upgrades, downgrades, version pins |
| Deployment | push, release, merge to main |

Non-consequential work gets a minimum stamp: `PRE-MORTEM · [action] · CLEAR — no consequential surfaces detected.`

## Output Format

```
╔══════════════════════════════════════════════════════════════╗
║  PRE-MORTEM  ·  [action in plain language]                   ║
╚══════════════════════════════════════════════════════════════╝

SURFACES DETECTED: [list]
DIMENSIONS CHECKED: [list]

[ TEMPORAL ]  ⚠ HIGH
  Adversarial: [direct statement of failure mode — no hedging, no "might"]
  Steelman: [strongest possible case this WILL fail — probability,
  mechanism, and consequence. Not "might." WILL.]
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

## 12 Failure Dimensions

Apply based on surfaces touched. All twelve for infrastructure; subset for architecture decisions; minimum stamp for everything else.

| # | Dimension | Key Questions |
|---|-----------|---------------|
| 1 | **Temporal** | Runs on schedule? Machine off? Edge times (midnight, month-end)? |
| 2 | **Concurrency** | Two instances simultaneously? TOCTOU races? Shared resource contention? |
| 3 | **Environmental** | Disk/memory pressure? Missing env vars? Network down? Permissions? |
| 4 | **Upgrade Durability** | Survives next package/OS upgrade? Config reset? Future dev accidentally reverts? |
| 5 | **Cascade** | What breaks downstream if this breaks? Hidden assumptions violated? |
| 6 | **Observability** | Errors logged? Alerting in place? Failure diagnosable from logs alone? |
| 7 | **Data Integrity** | Writes atomic? Safe if interrupted mid-write? Rollback path exists? |
| 8 | **Security** | New attack surface? Permissions over-scoped? Sensitive data exposed? |
| 9 | **Scale** | Works at N — what at 10N? Memory leaks over time? Disk accumulation? |
| 10 | **Human Factors** | Will next person understand? Could someone accidentally undo it? Documented? |
| 11 | **Recovery** | Blast radius? Rollback procedure? Kill switch? Manual override? |
| 12 | **Ecosystem** | Upstream bug worth reporting? Workaround creating debt? Dependency deprecation? |

Skip dimensions with no plausible failure path — don't manufacture risks.

## Adversarial Voice + Steelman Rules

- **Adversarial:** Names the failure mode directly. No hedging. No "might." No "could."
- **Steelman:** Makes the *strongest possible case* the failure is real and likely — not theoretical. Engages with probability, mechanism, and consequence. Goal: honest confrontation, not alarm.
- Apply steelman when there is a genuinely strong case. On clear dimensions, a brief CLEAR explanation suffices.

## Escalation Model

### Severity Tiers

**LOW** — flagged in checklist, does not block, logged to MemPalace as advisory.

**MEDIUM** — warns visibly, does not block, logged to MemPalace as advisory.

**HIGH** — blocks. Three-warning WarGames escalation before yielding.

**CATASTROPHIC** — blocks. Same escalation plus ceremony.
A risk is CATASTROPHIC when: irreversible AND blast radius extends beyond this session
(production data deletion, credential revocation, public infrastructure that cannot be
rolled back, actions affecting other users or systems outside this project).

### HIGH: WarGames Escalation (3 warnings then yield)

```
Warning 1:
  Present adversarial + steelman. Work is blocked.

Warning 2 (user persists):
  "To be clear: failure mode is [X], condition is [Y], consequence is [Z].
  Still proceeding?"

Warning 3 (user persists):
  "I need your reasoning before I can hand this over."

  User provides "here's why":
    ✓ Engages with steelman → "Acknowledged. Logging. It's on you."
    ✗ Hand-wavy / doesn't address the specific point →
      "That doesn't address [specific steelman point]. Try again."
```

### CATASTROPHIC: Ceremony (after Warning 3 + valid reasoning)

```
1. "State the action you are choosing to take." (verbatim — not just "proceed")
2. "State what you accept as the consequence."
3. "Keys confirmed. Logging. This is on you."
```

The user has the keys. If they choose to turn them with full knowledge, that is their
right. The skill's job is ceremony and documentation, not permanent veto.

## MemPalace Log

Every HIGH/CATASTROPHIC transfer gets logged via `mempalace_diary_write`:

```
[PRE-MORTEM TRANSFER] YYYY-MM-DD
Action: [verbatim]
Dimension: [which] — [severity]
Steelman: [full text]
User reasoning: [verbatim]
Reasoning engaged with steelman: yes / no
Responsibility: transferred to user
```

LOW/MEDIUM findings logged as advisories when relevant. No transfer record required.

## Instructions

1. Check action against surface list — identify applicable dimensions.
2. Run all applicable dimensions.
3. Skip dimensions with no plausible failure path.
4. For each real finding: adversarial statement → steelman → concrete mitigation.
5. Produce the visible checklist with severity summary and STATUS line.
6. Block on HIGH/CATASTROPHIC until resolved or escalation completes with valid reasoning.
7. Log HIGH/CATASTROPHIC transfers to MemPalace.
8. Non-consequential work: minimum stamp only.

## Red Flags — STOP, Run Pre-Mortem

- User says "we're done" or "ship it" after a fix to the surface list
- About to commit infrastructure, cron, hook, daemon, or config changes
- About to merge to main or push to prod
- Feeling time pressure ("meeting in 5 minutes")
- Just finished a long debugging session and want to be done
- ANY completion claim on work touching the surface list

## Rationalization Table

These are the thoughts that mean STOP — you are about to skip the pre-mortem:

| Rationalization | Reality |
|----------------|---------|
| "The fix is straightforward" | Straightforward fixes fail in production for non-obvious reasons. Cron timing, concurrent runs, and silent failures are not visible in the code. That is exactly what pre-mortem catches. |
| "We already tested it / verified it works" | `verification-before-completion` checks if it works now. Pre-mortem checks if it will keep working unattended, over time, across upgrades. Different questions. |
| "Time pressure — no time for analysis" | 5 minutes of pre-mortem now vs. hours of incident response later. The cron fires whether or not you are in a meeting. |
| "The user said we're done" | The user said the fix looks right. They did not enumerate failure modes — that is your job. |
| "Small change" | Size has no correlation with blast radius. An @reboot entry is one line. Temporal failures are catastrophic. |
| "We can fix issues if they come up" | Unattended systems fail silently. You will not know it came up until the damage has compounded. |

## Integration

| Skill | Relationship |
|-------|--------------|
| `verification-before-completion` | VBC = "works now?" Pre-mortem = "fails when?" Pre-mortem fires before commitment; VBC before completion claim. Complementary, not redundant. |
| `systematic-debugging` | Debugging finds root cause. Pre-mortem asks if the fix will hold. |
| `prior-art-check` | Runs first. Pre-mortem runs after action is decided. |
| `session-end-checklist` | Pre-mortem findings feed into session-end MemPalace snapshot. |

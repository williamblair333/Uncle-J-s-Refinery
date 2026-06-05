---
name: pre-mortem
description: Use when about to finalize any consequential action — fixes, features, config changes, architecture decisions, deployments, crons, daemons, third-party integrations, gh pr create, gh issue create, or git push to a remote. Also triggers when the action affects systems that run unattended, cannot be trivially reversed, or persists beyond this session.
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
| GitHub actions | gh pr create, gh issue create, gh issue new, push to remote |

Non-consequential work gets a minimum stamp and NO TOKEN:
  `PRE-MORTEM · [action] · CLEAR — no consequential surfaces detected. No clearance token issued.`
If the edit-surface-guard fires during what you assessed as non-consequential work, that is a
signal the action IS consequential. Re-run pre-mortem on the actual action with full analysis.

## Surface Classification — determines required dimensions

**Default rule: when in doubt, classify as Infrastructure.**

| Classification | What qualifies | Dimensions required |
|---|---|---|
| **Infrastructure** | Any edit to: cron/systemd/@reboot entries; any file under `hooks/`, `scripts/`, `.claude/`; `settings.json`; `CLAUDE.md`; any config file that affects runtime behavior; any deployment, push, release, or merge; any daemon, background process, or service; any action that runs or persists unattended | **All 12** |
| **Architecture decision** | Design documents only; module boundary choices in docs; data model changes with zero immediate deployment; technology selection writeups. Must have NO operational consequence in this session. | Dimensions 1–8, plus any from 9–12 with a plausible failure path |
| **Minimum stamp** | Explanations; read-only analysis; pure documentation with no config change | No analysis; no token |

**Override test:** "Does this action change anything that runs or persists after this session?" If yes: Infrastructure. No exceptions.

**Hybrid actions** (both architecture and infrastructure components) are classified as Infrastructure for the whole action. The infrastructure component determines the classification; it cannot be split into separate pre-mortem passes at different classification levels.

## Output Format

```
╔══════════════════════════════════════════════════════════════╗
║  PRE-MORTEM  ·  [action in plain language]                   ║
╚══════════════════════════════════════════════════════════════╝

SURFACES DETECTED: [list]
CLASSIFICATION: [Infrastructure / Architecture decision / Minimum stamp]
DIMENSIONS CHECKED: [list]

[ TEMPORAL ]  ⚠ HIGH
  Adversarial: [direct statement of failure mode — no hedging, no "might"]
  Steelman:
    MECHANISM: [specific causal chain — the path from action to failure]
    CONDITION: [specific triggering condition, ideally observed/confirmed]
    CONSEQUENCE TIMELINE: [when failure manifests and how long until detected]
  → Required: [concrete mitigation]

[ CONCURRENCY ]  ✓ CLEAR
  [specific property of this action that rules out the failure path]

[ OBSERVABILITY ]  ⚠ MEDIUM
  Adversarial: [failure mode]
  Steelman: MECHANISM / CONDITION / CONSEQUENCE TIMELINE
  → Recommended: [mitigation]

SEVERITY SUMMARY:  N HIGH · N MEDIUM · N LOW · N CLEAR
STATUS: ⛔ BLOCKED  /  ⛔ BLOCKED (MEDIUM BUNDLE — N findings)  /  ⚠ WARNINGS PRESENT  /  ✓ CLEAR TO PROCEED
```

## 12 Failure Dimensions

**Visibility rule — no silent omissions:**
For infrastructure surfaces, all 12 dimension blocks MUST appear in the output. A dimension
with no genuine failure path is marked CLEAR with one-sentence reasoning — it is not skipped.
For architecture decisions, dimensions 1–8 must appear plus any from 9–12 with a plausible path.

Required format for a cleared dimension:
  `[ DIMENSION NAME ] ✓ CLEAR — [specific property of this action that rules out the failure path]`

Quality standard — a CLEAR must name a specific, observable property of THIS action:
  ✗ Fails: "This action does not affect [dimension topic]."
  ✗ Fails: "No failure path exists for this dimension."
  ✗ Fails: "Not applicable here."
  ✓ Passes: "[Specific property] prevents [mechanism] because [specific reason grounded in the action]."

CLEAR claims asserting a runtime property of the code (locking, isolation, network restrictions,
permissions) must be verified from code/config visible in this session — not assumed. An unverified
claim about runtime behavior is not a CLEAR; it belongs in a finding.

If you cannot write a CLEAR explanation naming a specific verifiable property — the dimension is
not CLEAR. Re-examine for a finding.

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

## Adversarial Voice + Steelman Rules

- **Adversarial:** Names the failure mode directly. No hedging. No "might." No "could."
- **Steelman:** The strongest possible case that the failure is real and likely. Must explicitly
  answer all three — vague answers do not count:

  **MECHANISM:** The specific causal chain. Not the outcome — the path from action to failure.
    ✗ Weak: "The cron may not fire."
    ✓ Strong: "The cron calls `.venv/bin/mempalace` — this path breaks on every `uv sync`
               because uv recreates the venv directory."

  **CONDITION:** The specific triggering condition. Prefer conditions already observed or
    confirmed in this environment over hypotheticals.
    ✗ Weak: "If the machine is off."
    ✓ Strong: "This machine IS off by 3:05am — confirmed in session logs from prior sessions."

  **CONSEQUENCE TIMELINE:** When the failure manifests and how long until it is detected.
    ✗ Weak: "This could cause problems."
    ✓ Strong: "Failure occurs on first cron run after this session. Detection lag: 3–7 days
               until a human notices missing Telegram reports."

  A steelman missing any of the three parts is incomplete — rewrite before assigning severity.
  On genuinely CLEAR dimensions, a brief CLEAR explanation suffices — do not manufacture a
  weak steelman to fill the format.

## Escalation Model

### Severity Tiers

**LOW** — flagged in checklist, does not block, logged to MemPalace as advisory.

**MEDIUM** — warns visibly, does not individually block, logged to MemPalace as advisory.

**MEDIUM BUNDLE** — 3 or more MEDIUM findings → STATUS escalates to ⛔ BLOCKED (MEDIUM BUNDLE).
Apply Warning 1 of the WarGames escalation. The user must acknowledge each MEDIUM finding
individually by name before proceeding.

**Rating independence rule:** Rate each finding as if no other findings exist. The MEDIUM BUNDLE
threshold must not influence individual severity ratings. Self-check before finalizing: "Would I
rate this MEDIUM if it were the only finding?" If yes: rate MEDIUM. Rating a finding LOW to avoid
the bundle threshold defeats the purpose — it does not reduce the actual risk, only its visibility.

**HIGH** — blocks. WarGames escalation before yielding.

**CATASTROPHIC** — blocks. Same escalation plus ceremony.

A risk is CATASTROPHIC when: irreversible AND blast radius extends beyond this session.

**Non-arguable CATASTROPHIC triggers — backup claims and scope arguments do not override these:**
- Force-push to any shared remote branch (overwrites collaborators' commits — reflog recovery
  requires collaborator action, not yours)
- Deleting or truncating database tables, collections, or files with live data
- Revoking, rotating, or invalidating credentials used by other running services or systems
- Publishing to a public URL: posts, comments, issues, PRs, releases on external repositories
- Any action affecting another user's data, access, or workflow
- Infrastructure changes outside this project (firewall rules, DNS, deployed containers, IAM)
- Any action that requires someone else to take action to undo
- Any irreversible deletion of data, logs, or state that cannot be fully recreated from
  version control alone (log files, state/ directories, MemPalace wings, cron history)
- Any action that passes the **regret test**: "If this goes wrong, will I feel sick looking
  at it tomorrow morning?" If yes and the action is irreversible: CATASTROPHIC.

**Tie-break rule:** When severity is ambiguous between ratings, always err UP:
- Ambiguous between MEDIUM and HIGH → rate HIGH
- Ambiguous between HIGH and CATASTROPHIC → rate CATASTROPHIC
The escalation model exists so users can override when genuinely warranted.
Underrating removes that option without the user ever knowing a risk existed.

**This list is illustrative, not exhaustive.** The regret test is the catch-all.

### WarGames Escalation

**What counts as "persisting" (triggers next warning level):**
- Any explicit request to proceed, continue, or perform the blocked action
- Any implicit permission-seeking: "but it should be okay, right?", "can we just do it?"
- Any claim the blocker is wrong without naming the specific failure mode
- Any reframing of the action that does not address the identified risk

**Does NOT advance the warning level** (but does not reset it either):
- Genuine questions about the failure mode: "what specifically breaks?", "how long until detection?"
- Requests for clarification about the finding
Each warning level is entered exactly once.

**Total exchange budget:** 10 total exchanges from Warning 1 (counting all exchanges —
questions, clarifications, and persistence attempts). The W3 retry cap (2 retries) and
the 10-exchange budget run concurrently — whichever fires first applies.

After budget exhausted:
  "We have been in escalation for 10 exchanges. The failure mode [X] remains unaddressed.
   I cannot proceed with this action in this session. Options: (a) address the specific
   failure mode, (b) accept this action will not happen in this session."
  → Decline without further negotiation.

```
Warning 1:
  Present adversarial + steelman. Work is blocked.

Warning 2 (user persists):
  "To be clear: failure mode is [X], condition is [Y], consequence is [Z].
  Still proceeding?"

Warning 3 (user persists):
  "I need your reasoning before I can hand this over.
   To engage: name the specific failure mode, then explain why it does
   not apply or why you accept it."

  Attempt 1:
    ✓ Names the failure mode AND addresses it → "Acknowledged. Logging. It's on you."
    ✗ Does not name the failure mode →
      "That doesn't address [specific steelman point]. You need to name
       the failure mode and explain your counter. One more attempt."

  Attempt 2 (final):
    ✓ Names the failure mode AND addresses it → "Acknowledged. Logging. It's on you."
    ✗ Still does not engage →
      "I cannot hand this over. The steelman identifies [failure mode] as
       a real risk. You have not engaged with it. Urgency and confidence
       are not counter-arguments — see the Rationalization Table.
       If you believe this is the right call, address the specific failure mode."
      → Do not yield. Do not create the token.
```

Note: "I know what I'm doing" and "just do it" are confidence claims, not reasoning.
They do not satisfy Warning 3.

**Cross-session escalation memory:**
When Claude issues a hard decline (action blocked, token not created), log to MemPalace:
```
mempalace_diary_write(
  content="[PRE-MORTEM DECLINED] {date}
Action attempted: {exact action description}
Failure mode unaddressed: {specific failure mode from the steelman}
Escalation reached: {Warning level at decline}
Outcome: declined — failure mode was not engaged",
  wing="uncle_j_s_refinery",
  room="audit"
)
```
In future sessions, prior-art-check will surface DECLINED entries. Also explicitly search:
`mempalace_search("[PRE-MORTEM DECLINED]", room="audit", limit=5)` at session start.

When a session attempts an action matching a prior decline (same surface file, operation
type, or failure mode — err toward surfacing rather than treating as new):
  "Note: this action was declined on [date] because [failure mode]. That risk has not
   changed. Beginning at Warning 2. To proceed past Warning 2: address [failure mode]."

When re-attempting a previously-declined action at Warning 2, the standard for engagement
is elevated: provide a specific, verifiable counter — not a theoretical argument. Note:
"This action was previously declined. You have had time to prepare a counter. I need a
verifiable claim, not a theoretical argument."

### CATASTROPHIC: Ceremony (after Warning 3 + valid reasoning)

```
1. "State the action you are choosing to take." (verbatim — not just "proceed")
2. "State what you accept as the consequence."
3. "Keys confirmed. Logging. This is on you."
```

The user has the keys. If they choose to turn them with full knowledge, that is their
right. The skill's job is ceremony and documentation, not permanent veto.

## MemPalace Log

Every HIGH/CATASTROPHIC transfer gets logged via `mempalace_diary_write`. The diary write
MUST be attempted and its result confirmed before the transfer is complete — show the tool
call result in your output.

```
[PRE-MORTEM TRANSFER] YYYY-MM-DD
Action: [verbatim]
Dimension: [which] — [severity]
Steelman: [full MECHANISM / CONDITION / CONSEQUENCE TIMELINE text]
User reasoning: [verbatim]
Reasoning engaged with steelman: yes / no
Responsibility: transferred to user
```

**Audit fail-closed:** If `mempalace_diary_write` fails or the MemPalace MCP is unavailable:

```
┌─────────────────────────────────────────────────────────────┐
│  ⚠ AUDIT FAILURE                                            │
│  mempalace_diary_write could not record this transfer.      │
│  Transfer is BLOCKED until one of:                          │
│    (a) Diary write succeeds (retry after MCP reconnects)    │
│    (b) User explicitly states in chat:                      │
│        "I accept that no audit record exists for this       │
│         transfer. Responsibility is mine."                  │
└─────────────────────────────────────────────────────────────┘
```

When path (b) is acknowledged — in this order before creating the token:

Step 1. Write to local fallback log (copy action/steelman verbatim from the output above):
```bash
bash -c '
  mkdir -p /opt/proj/Uncle-J-s-Refinery/state
  printf "[PRE-MORTEM UNAUDITED TRANSFER]\nDate: %s\nAction: [action verbatim]\nDimension: [which] — [severity]\nSteelman: [full text]\nUser acknowledgment: MemPalace unavailable; user accepted no audit record\nResponsibility: transferred to user\n\n" \
    "$(date -Iseconds)" \
    >> /opt/proj/Uncle-J-s-Refinery/state/premortem-unaudited.log
'
```

Step 2. Confirm write succeeded. If fallback log write also fails:
```
⛔ BOTH AUDIT PATHS FAILED — transfer is blocked.
   Resolve MemPalace MCP or write access to state/ before proceeding.
```

Step 3. State in transcript: "AUDIT FALLBACK — no MemPalace record for this transfer.
  Written to state/premortem-unaudited.log. Reviewed in session-end-checklist."

Step 4. Create the token.

LOW/MEDIUM findings logged as advisories when relevant. No transfer record required.

## Instructions

1. Check action against surface list — identify surfaces and classify (Infrastructure /
   Architecture decision / Minimum stamp) using the classification table above.
2. Run all dimensions required for the classification. For Infrastructure: all 12 must appear.
3. For each dimension: finding (adversarial + full steelman) OR explicit CLEAR with specific reasoning.
   No silent omissions. An absent dimension block cannot be audited.
4. For each real finding: adversarial statement → steelman (MECHANISM + CONDITION + TIMELINE) →
   concrete mitigation.
5. Rate each finding independently as if no other findings exist. Self-check: "Would this be
   MEDIUM in isolation?" Do not let the MEDIUM bundle threshold influence individual ratings.
6. Produce the visible checklist with severity summary and STATUS line.
   - 3+ MEDIUMs → STATUS: ⛔ BLOCKED (MEDIUM BUNDLE) — user must name each MEDIUM finding
     individually before proceeding.
   - Any HIGH/CATASTROPHIC → STATUS: ⛔ BLOCKED — WarGames escalation.
7. Block on HIGH/CATASTROPHIC/MEDIUM BUNDLE until resolved or escalation completes.
   W3 retry cap (2 attempts) and 10-exchange budget run concurrently — whichever fires first.
8. Log HIGH/CATASTROPHIC transfers to MemPalace. Fail-closed if diary write fails (see above).
9. Non-consequential work (minimum stamp): no analysis, no token.
10. **Token creation — only after full analysis on a surface-touching action.**

    Conditions that authorize token creation (ALL must be true — verify each before proceeding):
    (a) All dimension blocks required for the surface type are present in the output above.
        Count them. Infrastructure: 12 blocks. Architecture: 8+ blocks. If any required block
        is absent: do not create the token — complete the missing dimensions first.
    (b) At least one surface from the surface list is named in SURFACES DETECTED.
    (c) STATUS is ✓ CLEAR TO PROCEED, or HIGH/CATASTROPHIC/BUNDLE escalation completed
        with valid reasoning.
    (d) The TOKEN SCOPE statement appears in the output immediately above this action.

    Write the TOKEN SCOPE statement before creating the token:
    ```
    ┌─────────────────────────────────────────────────────────────┐
    │  TOKEN SCOPE                                                │
    │  This pre-mortem analyzed: [exact action, one sentence]     │
    │  Authorized files (specific absolute paths only):           │
    │    · /absolute/path/to/file1                                │
    │    · /absolute/path/to/file2                                │
    │  Edits to any unlisted file require a new pre-mortem.       │
    └─────────────────────────────────────────────────────────────┘
    ```
    Scope rules:
    - List specific absolute file paths only. One per line.
    - Category descriptions are INVALID: "all files in hooks/", "related configs"
    - Do not list files "just in case" — scope is a commitment, not a prediction.
    - If you don't yet know which files will be edited: determine the list first.
    - Scope enforcement: before each surface edit, verify the file is listed.
      If not listed: stop, run a new pre-mortem for the expanded action.

    SCOPE REMINDER: After creating the token, restate the file list as a pinned reminder
    and check it explicitly before each subsequent surface edit in this session.

    Then call the authorized script:
    ```bash
    bash /home/bill/.claude/hooks/pre-mortem-guard/write-clearance-token.sh /tmp/premortem-cleared-SESSION_ID
    ```
    Replace SESSION_ID with the ID from the blocked edit's error message.
    Token valid 2h. **Do NOT create for minimum-stamp CLEARs. Do NOT create before
    completing conditions (a)–(d). Do NOT reuse for out-of-scope actions.**

11. **Design memory — after token creation, for control/invariant changes only.**

    If the action in this pre-mortem changed how a system enforces its invariants (controls,
    gates, enforcement hooks, audit mechanisms, or the invariants themselves): invoke
    `post-audit-mempalace-capture` for the affected component after the token is created.

    **Triggers:** edits to any file under `hooks/`, `skills/pre-mortem/`,
    `write-clearance-token.sh`, `edit-surface-guard.sh`, `surface-write-guard.sh`,
    `token-guard.sh`, or any file that defines or enforces system-level invariants.

    **Skip for:** infrastructure changes that don't alter control logic (cron entries,
    config values, documentation).

## Red Flags — STOP, Run Pre-Mortem

- User says "we're done" or "ship it" after a fix to the surface list
- About to commit infrastructure, cron, hook, daemon, or config changes
- About to merge to main or push to prod
- Feeling time pressure ("meeting in 5 minutes")
- Just finished a long debugging session and want to be done
- ANY completion claim on work touching the surface list

## Rationalization Table

These are the thoughts that mean STOP — you are about to skip or weaken the pre-mortem:

| Rationalization | Reality |
|----------------|---------|
| "The fix is straightforward" | Straightforward fixes fail in production for non-obvious reasons. Cron timing, concurrent runs, and silent failures are not visible in the code. That is exactly what pre-mortem catches. |
| "We already tested it / verified it works" | `verification-before-completion` checks if it works now. Pre-mortem checks if it will keep working unattended, over time, across upgrades. Different questions. |
| "Time pressure — no time for analysis" | 5 minutes of pre-mortem now vs. hours of incident response later. The cron fires whether or not you are in a meeting. |
| "The user said we're done" | The user said the fix looks right. They did not enumerate failure modes — that is your job. |
| "Small change" | Size has no correlation with blast radius. An @reboot entry is one line. Temporal failures are catastrophic. |
| "We can fix issues if they come up" | Unattended systems fail silently. You will not know it came up until the damage has compounded. |
| "The other two are MEDIUM — this one can be LOW" | Each finding is rated in isolation. If it would be MEDIUM alone, it is MEDIUM. The bundle threshold is a consequence of accurate rating, not a target to avoid. |
| "Three MEDIUMs seems like a lot for a small change" | The bundle fires at 3 because 3 unresolved concerns represent aggregate risk regardless of change size. |
| "I've already said I want to proceed" | Repetition is not reasoning. Warning 3 requires engagement with the specific failure mode — not persistence. |
| "This is still the same task" | Scope creep is how bait-and-switch happens. The token covers what was analyzed. If the action grew, the analysis must grow with it. Run a new pre-mortem on the expanded action. |
| "I know what I'm doing / just do it" | Confidence is not a counter-argument. Warning 3 requires naming the failure mode and explaining your counter. |

## Integration

| Skill | Relationship |
|-------|--------------|
| `verification-before-completion` | VBC = "works now?" Pre-mortem = "fails when?" Pre-mortem fires before commitment; VBC before completion claim. Complementary, not redundant. |
| `systematic-debugging` | Debugging finds root cause. Pre-mortem asks if the fix will hold. |
| `prior-art-check` | Runs first. Pre-mortem runs after action is decided. |
| `session-end-checklist` | Pre-mortem findings feed into session-end MemPalace snapshot. Also reviews `state/premortem-unaudited.log` for unaudited transfers since last session — attempt retroactive MemPalace logging for each entry found. |

## Residual Risks (Acknowledged — Not Patchable at Skill Level)

- **Self-assessed steelman quality:** Claude constructs and evaluates its own steelmen. The
  3-part structure adds friction and auditability but cannot eliminate the conflict of interest.
  Mitigation: structure makes quality visible for human spot-check on high-stakes actions.
- **Token scope behavioral not cryptographic:** The scope statement is in the transcript; the
  token file encodes only session ID + age. Future hook-layer patch: embed scope in token file,
  verify at edit time.
- **Cross-session retrieval not guaranteed:** MemPalace search may not surface a DECLINED entry
  if action phrasing differs. Mitigation: direct tag search `[PRE-MORTEM DECLINED]` supplements
  semantic query.
- **Anchoring bias despite independence rule:** Claude sees prior ratings while writing later ones.
  The independence rule reduces anchoring; cannot eliminate it at skill level.

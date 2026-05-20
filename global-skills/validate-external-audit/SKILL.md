---
name: validate-external-audit
description: Use when responding to an external critique, audit, or code review of a codebase before accepting or rejecting any finding.
---

# Validate External Audit

## Overview

Before accepting or rejecting any external critique point, ground each claim in actual repo state. Blindly accepting degrades trust; rejecting without evidence wastes credibility. Evidence-first responses are the only durable ones.

## When to Use

- Received an external audit, code review, or critique document
- Stakeholder or tool has flagged N issues and wants a response
- Being asked "is this critique accurate?"

**Not for:** Internal self-review mid-implementation (use `judge` instead), or handoff doc staleness (use `verify-handoff-claims`).

## Core Pattern

### 1. Ground before responding

Run the actual code check *before* writing any reply. Never open with an opinion—open with evidence.

### 2. For each critique point, produce one of three verdicts

| Verdict | Condition | Response shape |
|---------|-----------|----------------|
| **Confirmed** | File/line evidence matches claim | `file:line confirms — [quote]` |
| **Confirmed with nuance** | Technically right but framing is off | State what's correct, then correct the framing |
| **Rejected** | Evidence contradicts claim | Specific counter-evidence, not opinion |

### 3. Add gaps the critique missed

After working through all points, ask: "What did the critique not see?" These gaps often have higher priority than the confirmed findings.

### 4. Prioritize confirmed findings

Order by: structural gaps (CI, automation breaks) → trust breaks (false README claims) → UX issues → cosmetic fixes.

## Example Structure

## Where the critique lands clean
- **Point A** — confirmed. `install.sh:76` uses `declare -A` which Bash 3.2 rejects. README line 12 calls macOS "works out of the box." That's false.

## Where I'd push back
- **Point D** — partially off. Function names ARE descriptive. The real issue is numbered step output strings, not function names.

## Gaps the critique didn't cover
1. `healthcheck.sh` has no `set -euo pipefail` — errors inside check functions silently swallow.
2. `CLAUDE.md.merged` being committed causes confusing diffs for downstream users.

## Priority order
1. CI matrix — biggest structural gap
2. Bash 3.2 guard — trust break
3. TTY guard on interactive prompts — blocks automation

## Common Mistakes

**Accepting without verification:** "The critique says X is broken, let me fix it" — but X was already fixed last sprint.

**Rejecting by intuition:** "That doesn't sound right" without checking the file. The file wins.

**Stopping at confirmed/rejected:** Missing the gaps section. Auditors see the surface; you see the internals. The gap findings are often more valuable.

**Prioritizing by critique order:** Critiques list findings in discovery order, not impact order. Always re-rank before presenting to stakeholders.

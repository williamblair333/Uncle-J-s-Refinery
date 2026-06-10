---
name: smart-review
description: Auto-classifying code review router. Applies a deterministic rules floor + independent shadow classifier to pick the right review depth, then dispatches to code-review (low/medium/high) or adversarial-review (critical). Logs every classification decision to MemPalace for drift audit.
when_to_use: Whenever code has changed and needs review — replaces manually picking an effort level. Default entry point for all code review.
---

# Smart Review — Auto-Classifying Router

## Step 0 — Get the diff

```bash
git diff @{upstream}...HEAD 2>/dev/null || git diff main...HEAD 2>/dev/null || git diff HEAD~1
git diff --name-only @{upstream}...HEAD 2>/dev/null || git diff --name-only HEAD~1
```

If an argument was passed (PR number, branch, file path), use that as the target instead. Also capture `git diff HEAD` if there are uncommitted changes.

Capture:
- `DIFF_STAT`: total lines added + removed (`git diff --stat`)
- `FILES_CHANGED`: list of changed file paths

---

## Step 1 — Rules floor (deterministic, no model judgment)

Match `FILES_CHANGED` against the table below. The HIGHEST matching tier is the floor. If nothing matches, floor = **Medium**.

| Pattern in any changed file path or content | Floor tier |
|---|---|
| `auth`, `session`, `token`, `password`, `credential`, `secret`, `permission`, `oauth`, `jwt`, `api_key`, `.env` | **Critical** |
| `hooks/`, `.claude/`, `settings.json`, `CLAUDE.md`, `*.service`, `cron`, `systemd`, `@reboot` | **Critical** |
| `migration`, `schema`, `ALTER TABLE`, `DROP TABLE`, `DROP COLUMN` | **Critical** |
| Any file the pre-mortem fired on in this session, AND the change goes beyond what the pre-mortem cleared | **Critical** (floor enforced by collision) |
| Any file the pre-mortem fired on in this session, AND the change IS exactly what the pre-mortem cleared | **High** (collision floor; pre-mortem already covered the risk) |
| New function or class added (diff contains `^+.*def ` or `^+.*class ` or `^+.*function `) | **High** |
| API route added or changed (diff contains `@app.`, `@router.`, `router.get`, `router.post`, `app.use`) | **High** |
| Diff > 150 lines changed | **High** |
| Diff 50–150 lines changed | **Medium** |
| Only `.md`, `.txt`, `.css`, comments, or whitespace changed | **Low** |

Tie-break rule: **always escalate, never downgrade**. Ambiguous = one tier up.

Record: `FLOOR_TIER`

---

## Step 2 — Shadow classifier (independent agent, adversarial upward bias)

Dispatch one Agent with this exact prompt — do NOT pass it the floor tier or your own assessment:

> "You are classifying a code diff for review depth. Your bias is upward — when uncertain, return the HIGHER tier, not the lower. Do not justify your decision with caveats.
>
> Tiers: Low (docs/comments/CSS only), Medium (routine feature/fix), High (complex logic, new API, significant refactor), Critical (auth/security/infrastructure/hooks/config that affects runtime).
>
> Diff stats: {DIFF_STAT}
> Files changed: {FILES_CHANGED}
> Diff:
> {DIFF}
>
> Return exactly: TIER: <Low|Medium|High|Critical> — <one sentence reason>"

Record: `SHADOW_TIER`

---

## Step 3 — Resolve

`RESOLVED_TIER = MAX(FLOOR_TIER, SHADOW_TIER)`

Tier ordering: Low < Medium < High < Critical.

If floor and shadow agree: proceed.
If they disagree: log the discrepancy (see Step 5), use the higher.

---

## Step 4 — Dispatch

| Resolved tier | Action |
|---|---|
| **Low** | Invoke `code-review` skill with `--effort low` argument |
| **Medium** | Invoke `code-review` skill with `--effort medium` argument (default) |
| **High** | Invoke `code-review` skill with `--effort high` argument |
| **Critical** | Invoke `adversarial-review` skill — pass the diff/target as args |

Tell the user: `"[SMART-REVIEW] Floor: {FLOOR_TIER} | Shadow: {SHADOW_TIER} | Resolved: {RESOLVED_TIER} → dispatching {tool}"`

---

## Step 5 — Drift audit log (MemPalace)

After every review, write a classification record:

```
mempalace_diary_write(
  content="[SMART-REVIEW CLASSIFICATION]
Date: {date}
Files: {FILES_CHANGED}
Diff size: {lines added/removed}
Floor tier: {FLOOR_TIER} (rules matched: {which rules fired})
Shadow tier: {SHADOW_TIER} (shadow reason: {shadow one-liner})
Resolved tier: {RESOLVED_TIER}
Disagreement: {yes/no — if yes, floor was X, shadow was Y}
Review dispatched: {code-review effort={level} | adversarial-review}",
  wing="uncle_j_s_refinery",
  room="review_audit"
)
```

---

## Drift audit review (periodic)

When the `session-end-checklist` runs, or on request, scan MemPalace for recent `[SMART-REVIEW CLASSIFICATION]` entries and check:

- How often did floor and shadow disagree?
- Which file paths am I consistently under-classifying?
- Any `Low` classification that touched a file matching a Critical pattern? → that's a rules bug, tighten the table.

If a pattern emerges → add a new row to the rules floor table and update this skill.

---

## Step 6 — Write clearance marker

After the review completes (findings returned or adversarial-review concludes), run:

```bash
HEAD_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
touch "/tmp/smart-review-cleared-${HEAD_SHA}"
echo "[SMART-REVIEW] Clearance marker written: /tmp/smart-review-cleared-${HEAD_SHA}"
```

This marker is consumed by the PreToolUse hook on `git push` and `gh pr create`. Without it those commands are blocked. The marker is scoped to the current HEAD SHA — a new commit invalidates it.

---

## Notes

- This skill is the default entry point. Users and Claude should call `/smart-review` instead of manually picking `/code-review --effort X`.
- Shadow classifier result is advisory only if floor is Critical — Critical cannot be downgraded by shadow.
- The shadow agent has upward bias by prompt design. If it says Medium and floor says Low, Medium wins. If it says Low and floor says Medium, Medium wins. Low can only come from unanimous agreement.
- `verification-before-completion` (`superpowers:verification-before-completion`) checks functional correctness. This skill checks code quality and safety. They are complementary — run both before merging anything High or Critical.

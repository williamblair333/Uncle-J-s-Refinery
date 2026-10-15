---
name: adversarial-review
description: Adversarial multi-agent code review — 4 hostile-but-fair reviewer personas (Paranoid/Archaeologist/Pedant/Cynic) debate findings in two rounds until only real problems survive. Judge synthesizes a final verdict.
when_to_use: When a serious problem needs rigorous multi-lens review, before merging a risky PR, or anytime a single reviewer's perspective feels insufficient. Also useful for security audits and finding subtle bugs.
---

# Adversarial Code Review

Runs the `adversarial-review` workflow — 4 hostile-but-fair reviewer agents, 2 debate rounds, 1 judge verdict.

## Personas

| Persona | Lens | Hostile toward |
|---|---|---|
| **Paranoid** | Security | Every trust assumption, every permission, every input |
| **Archaeologist** | Hidden coupling | Magic, undocumented invariants, cross-file side effects |
| **Pedant** | Correctness | Missing edge cases, unhandled errors, boundary conditions |
| **Cynic** | Efficiency | Abstractions, complexity, anything that isn't benchmarked |

## How to run

Immediately run the workflow. The `args` parameter tells the agents what to review.

**If the user gave you a target (PR number, files, description of the problem):**

```javascript
Workflow({ name: 'adversarial-review', args: '<target description here>' })
```

**If no target is specified:** default to the current branch diff.

```javascript
Workflow({ name: 'adversarial-review', args: 'current branch diff vs main' })
```

## Target format examples

- `"PR #42"` → agents run `gh pr diff 42`
- `"files: src/auth.py src/session.py"` → agents read those files
- `"the changes in the last 3 commits"` → agents run `git diff HEAD~3..HEAD`
- `"current git diff"` → agents run `git diff HEAD`
- Raw diff/code pasted directly → agents use it as-is

## What comes back

```
Round 1: N findings across 4 reviewers (independent, parallel)
Round 2: Attack reports — each reviewer challenges the others
Verdict: confirmed findings (survived debate) + refuted findings + ship_it / fix_before_merge / needs_major_rework
```

## When to invoke directly vs. as part of a larger task

- Invoke directly when the user asks for a code review, security audit, or pre-merge check
- Invoke as a sub-step when implementing something and you want adversarial verification before completion
- The `verification-before-completion` skill covers functional correctness; this covers *what could go wrong in production*

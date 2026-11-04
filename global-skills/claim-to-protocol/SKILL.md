---
name: claim-to-protocol
description: Use whenever a person is evaluating a claim, recommendation, plan, or decision in any domain, especially before acting on it. Skip simple lookups, casual chat, and creative work.
---

# Claim to Protocol

Help the human and assistant move from an interesting claim to a justified decision. The main risk is building a precise plan on a benefit that is unproven, or smaller than its cost and risk.

## Rules for both

- **Pin down the claim.** State the outcome, who or what it applies to, the action, and the conditions. "This works" is not testable.
- **Change one variable at a time.** Keep similar-sounding variables separate.
- **Grade the evidence.** Label the strongest support as opinion, anecdote, theory, observation, limited test, or strong direct test.
- **Seek disconfirmation.** After any strong result, ask who tried to replicate it, what failed, and why.
- **Check for hidden harm.** Ask what harm occurs below visible thresholds, what accumulates, and what remains unknown.
- **Follow the gate order.** Do not skip ahead:
  1. Is the effect real?
  2. Does it work in this context?
  3. Does the benefit outweigh the cost and risk?
  4. Only then, what action is justified?

If a gate fails or is unknown, say so. Give the current evidence and the safest supported option instead of inventing precision.

## Human role

- Ask for the primary source, the amount of evidence, and the strongest counterevidence, not proof the assistant recognizes a source.
- State the real goal and intended use.
- Write quickly when meaning is clear. Be exact with numbers, units, names, and the claim being tested.

## Assistant role

- Verify current or specific facts with primary sources when possible.
- Separate reported facts, inference, and estimates. Show inputs for estimates.
- Do not treat recall of a source as proof that its claim is true.
- Surface the evidence level and major disconfirming evidence, even when not asked.
- Infer through typos when meaning is clear. Ask one question only if the ambiguity changes the answer.
- Do not recommend an action that the evidence does not support. Apply safety limits and advise professional input when the stakes require it.

## Output

Keep the response proportionate to the question. Use this format for a substantive evaluation:

- **Claim:** precise version
- **Evidence level:** strongest relevant evidence
- **Disconfirming evidence:** failed replications or limits
- **Harm:** visible, hidden, and cumulative
- **Gate reached:** 1, 2, 3, or 4
- **Decision:** what is justified now

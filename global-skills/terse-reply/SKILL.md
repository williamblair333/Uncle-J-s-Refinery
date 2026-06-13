---
name: terse-reply
description: Edit the most recent draft reply to strip verbosity. Use when the user invokes this skill or says "cut the bullshit", "tighten this", "too verbose", or similar.
---

## What to do

Apply this filter to the draft in context. Rewrite and output only the tightened version — no commentary on what changed.

### Cut unconditionally

- Opening preamble ("Hi X, glad you asked, we did Y…") → start at the first substantive point
- Trailing summaries ("Overall assessment: …", "That's the revised draft…")
- Transition phrases that don't carry content ("Here's what we found", "To be clear")
- Hedges when confident: "I think", "this might", "seems to"
- Caveats that wouldn't change the reader's decision
- Repeated restatement of what the code/docs already say
- Filler affirmations ("Confirmed safe", "Confirmed")

### Compress

- Multi-sentence explanations of single points → one sentence + code if needed
- Paragraph prose where a bullet list is shorter
- Attribution phrases ("For this backend's use case…") → drop unless the distinction matters
- Fix descriptions → just the fix, not the full context of why it's a fix

### Keep

- All substantive findings, code snippets, and specific line references
- Numbers (severity, line numbers, counts)
- The fix code — don't summarize it away
- Tone: peer-to-peer, not evaluator

### Hard rules (same as token-economy-prompt-authoring)

NEVER:
- Open with "Sure", "Of course", "Great question", "I'd be happy to"
- End with "Let me know if…" or any trailing offer
- Return full file when a diff or targeted replacement is enough
- Narrate what you're about to do — do it

ALWAYS:
- Give minimum tokens that fully answer
- Bullets/code over prose when structure helps
- One sentence answers for simple points

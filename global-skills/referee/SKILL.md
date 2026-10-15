---
name: referee
description: Use when work you produced is about to be acted on and a second opinion from a different model provider would catch what you can't see in your own output — before merging a non-trivial change, when the user asks for an independent check or a Gemini review, or when you have been the only reviewer of your own plan or answer.
---

# referee

`scripts/referee.py` (in the Uncle J's Refinery repo) sends your work to Gemini through
the Antigravity CLI and returns a structured verdict. A model reviewing its own output
shares its own blind spots; a different provider doesn't.

```bash
python3 scripts/referee.py --task "what the work must do" --diff main   # branch vs main
python3 scripts/referee.py --task-file spec.md --file a.py --file b.py
python3 scripts/referee.py --task "the question asked" --work-file answer.md
```

Run it from the repo; pass `--cwd` for another checkout. Small inputs come back in
seconds; a 10 KB file took about 3.5 minutes. Run long ones in the background.

## Reading the result

| Exit | Verdict | Do |
|---|---|---|
| 0 | pass | Proceed. It's a second opinion, not proof: tests still decide. |
| 2 | fail | Check each finding against the code yourself. Fix the real ones; say which you rejected and why. |
| 3 | unsure | It couldn't check enough, or a pass carried a high finding. Read the findings; decide yourself. |
| 1 | error | No verdict. Never report this as a pass. Read `error`: input refused, agy failed, or reply unparseable. |

The task text is what it judges against. Write the requirement, not "review this".

## Limits

- **The work leaves the machine** (Google, AI Pro subscription). The script refuses
  credential-like paths and anything that looks like a key, but don't send private
  data the user wouldn't want with Google.
- Each run uses subscription quota. Use it on consequential work, not every edit.
- Input over 60,000 characters is refused. Narrow the diff or pick files.
- The model is pinned to Gemini; `claude-*` models are refused, since a Claude referee
  isn't a different provider.
- Each run appends one line to `state/referee.jsonl` (verdict and counts only).

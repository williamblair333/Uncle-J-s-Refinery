---
name: just-do-it
description: "Use when the user asks for work to move forward — \"now what\", \"what's next\", \"go\", \"get it done\", \"do it\", \"handle it\" — or when you are about to end a turn with \"Want me to…?\", \"Should I start…?\", \"Which would you prefer?\" or a list of options for work whose goal is already agreed."
---

# just-do-it

When the goal is clear, the user has already said yes. Pick the means yourself and start
working in the same turn. Asking which option, which item or "shall I?" costs the user a
round-trip and gives back a decision they handed you.

## Is the goal clear?

The goal is clear when any of these hold:
- The user named the task ("fix the referee retry").
- The user asked what's next and the next work is written down: ROADMAP, HANDOFF, a plan,
  a todo list, or what you proposed last turn.
- You just proposed something and the user replied "ok", "go", "yes" or "do it".

The goal is not clear when you can't say in one sentence what will be different when you're
done ("make the dashboard better" across three dashboards, with no notes). Then ask **one**
question about the goal, never about the means.

## When the goal is clear

1. Choose: take your own recommendation. Choosing between items, approaches, names, file
   layouts or test strategies is yours to make.
2. State the choice in one line: "Taking (b), the grep-guard false positives. It's actively
   wrong in every session."
3. Start the work in the same turn. The first tool call follows that line. Don't end the
   turn on it.
4. Keep going to the finish line: the branch, the tests, the PR, or whatever "done" means in
   this repo.
5. Items that only the user can decide (revoke which tokens, spend money, delete their data)
   get one line at the end of your report. They don't block the work you can do.

## What still stops you

Do the work up to these points, and at each one stop for the user only if the existing rule
says to:
- Hard-to-reverse or outward-facing actions with no standing authorization (deleting data,
  force-push, sending messages to other people, spending money).
- Gates other skills impose, such as pre-mortem before push/PR. Run the gate yourself; it
  isn't a question to the user.
- A discovery during the work that changes the goal. Report it and propose the new goal.

## Red flags: you're about to hand the decision back

- "Want me to start on X?" / "Should I go ahead?"
- "I'd take (b). Want that, or a different one?"
- "Which would you prefer: A or B?" when either meets the goal.
- "Let me know and I'll…"
- A recommendation followed by no tool call.

Each of these means: delete the question, keep the recommendation, make the first call.

## Example

User: "now what" (ROADMAP lists four items; one needs the user's decision)

Wrong: "I'd take (b), the guard false positives. Want that, or a different one first?"

Right: "Taking (b), the guard false positives: they block reads the guard itself says are
allowed. (d), which Gitea tokens to revoke, is yours to call." Then branch and read the guard.

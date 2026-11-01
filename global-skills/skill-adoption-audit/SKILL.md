---
name: skill-adoption-audit
description: Use when a skill or memory note was installed to fix a recurring agent failure, but the failure happened again. Typical prompts are "did that session even use the skill?", "why did I have to ask again?" or "are the skills firing in project X?". Checks whether sessions actually called the skills, then moves the fix from "the model remembers" to a mechanical check.
---

# Skill Adoption Audit

## When to use
- A skill (for example `expert-bar`, `think-wider` or `slowest-loop-first`) is installed globally to stop a failure, and the user reports the same failure again.
- The user's complaint closely matches a listed trigger for a skill, and you want to know whether the session called that skill.
- A project keeps writing memory notes about the same mistake.

## Core idea
Being installed doesn't mean being used. A model deep in a long session rarely reaches for optional skills or memory notes. Measure what the sessions actually did. Then take the fix out of the model's hands with a script gate or a hook.

## Steps

1. **Confirm installation and visibility.** Check that the skills are installed globally and that they appeared in the target session's skill list. This rules out "it couldn't see them."

2. **Profile the session in question.** Record:
   - start time and how long it ran
   - transcript length in lines
   - whether it was ever compacted

   Long sessions with no compaction are where optional skills get dropped.

3. **List skill calls against available skills.** From the transcript, list every skill the session actually called. Compare that with the relevant skills in its skill list. Report each relevant skill that was available but never called.

4. **Match the complaint to triggers.** Compare the user's wording with each skill's description and triggers. If the complaint is close to a listed trigger (for example "why did I have to…" against `expert-bar`), the trigger failed in practice.

5. **Find what the session did instead.** Look for a substitute such as a new project memory note. Flag it when it repeats a fix that has already failed, like a note the model may or may not read next time.

6. **Widen to every session in the project since the skills were installed.** Count calls per skill. A skill that ran once or never across many sessions is not being adopted.

7. **Check whether the rule was already written down.** Search the project's `STANDARDS.md` (or similar) for the rule that would have prevented the failure. If it's there, the gap is that nothing makes the session check it.

8. **Report.** Lead with a direct yes or no on "do the sessions use the skills when it counts". Back it with the counts and file evidence (`file:line`).

## Fix pattern: make it mechanical
Propose enforcement that doesn't depend on the model remembering:

- **A project-side gate in the relevant launcher or script.** It refuses to proceed until each known failure condition has been ruled out or neutralised. Before writing the gate, check what the project already handles, so the gate lists only the uncovered cases.
- **A global prompt hook for complaint phrases** ("why did I have to", "you should have seen" and similar). It forces the relevant skills to run, so the fix lands in STANDARDS plus a check rather than a memory note.
- **A replay bench for the hook** on real transcripts that reports its fire rate and false hits. This meets a behaviour-bench-per-hook standard.

Put each fix in the repo it belongs to, on its own branch: the gate in the project repo, the hook in the stack repo.

## Anti-patterns
- Writing yet another memory note as the fix.
- Concluding that skills work because they're installed and listed.
- Building a gate before checking what the project already covers.

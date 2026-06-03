---
name: audit-pipeline-fabrication-risk
description: Systematically audit an AI pipeline for hallucination/fabrication propagation paths — where model-generated content (especially URLs, issue numbers, citations) can reach persistent stores without verification. Use when another agent has identified a fabrication risk but you need code-grounded verification before building fixes.
---

## When to Use

- Another agent or session flagged a fabrication/hallucination propagation risk in a pipeline
- You need to verify whether proposed fixes are grounded in what the code actually does
- A pipeline writes model-generated content to persistent stores (CLAUDE.md, MemPalace, databases, cron scripts)
- You want to identify the highest-leverage intervention point before building

## Key Steps

### 1. Check MemPalace First
mempalace search: "<pipeline name> fabrication risk"
Prior sessions may have already mapped propagation paths or attempted fixes.

### 2. Read the Actual Pipeline Code
Do not trust prose descriptions of what the pipeline does. Read the source:
- Find the script/skill that synthesizes model output
- Trace the data flow: where does output go? What transformation happens before storage?
- Look for what is **not** filtered (often more revealing than what is)

### 3. Verify Specific Claims Against Code
For each proposed fix or risk claim, check the actual code:
- Does flag X exist? Run `--help` or read the CLI source
- Does threshold Y work the way it's described? Read the synthesizer prompt/logic
- What does "filtered" actually mean in this context? Pattern-level or locator-level?

Common precision failures to catch:
- "Fires at emit time" vs. "fires at session end" — these have very different blast radii
- "2-session threshold filters fabrications" vs. "threshold filters single-incident noise" — behavioral patterns recur across sessions even if individual URLs differ
- "Tagging flag available" vs. "flag does not exist" — check `--help` before proposing flag-based solutions

### 4. Map the Propagation Chain
Identify every store the pipeline writes to:
grep -n "mempalace mine\|>> ~/.claude\|CLAUDE.md\|append" <pipeline_script>
Each write site is a potential propagation gate. Rank by blast radius:
- Writes to standing instructions (CLAUDE.md) > writes to memory wings > writes to logs

### 5. Identify the Highest-Leverage Gate
The gate that prevents propagation is more valuable than the gate that audits after the fact:
- A **pre-write filter** inside the pipeline script stops content from reaching the store
- A **post-session audit hook** creates signal but cannot retroactively block what already reached the user or was stored

If both options exist, build the pre-write filter first.

### 6. Propose Concrete, Code-Grounded Fixes
Reference specific line numbers:
# dream.sh line 164: mempalace mine call
# dream.sh line 187: CLAUDE.md append
# Fix: grep $SYNTHESIS for URL patterns before both writes

Fixes that cannot be verified against actual code should be marked as assumptions pending verification.

## Anti-Patterns to Avoid

- **Trusting inferences about flags or thresholds** — always verify against `--help` or source
- **Assuming "filtered" means "filtered for your concern"** — synthesis may strip PII but not URLs
- **Conflating audit hooks with prevention hooks** — session-end hooks are post-hoc, not gates
- **Proposing flag-based solutions before confirming the flag exists**

## Output Format

Report findings in three sections:
1. **Gap confirmed / not confirmed** — what the code actually shows
2. **Correction to prior framing** — where prior analysis was imprecise
3. **What would actually get built** — line-specific, code-grounded fix proposals

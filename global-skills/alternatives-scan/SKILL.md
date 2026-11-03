---
name: alternatives-scan
description: Use when the user asks you to look at, review, analyze or evaluate a tool, library, engine, model, app, service or a plan that commits to one; asks "is X good", "should I use X", "X vs Y", "anything better than X", "alternatives to X"; or before downloading, cloning or installing something new (the download gate blocks until a scan exists). Finds what else does the same job, maybe worlds better, and judges it against the user's goals and use cases.
---

# alternatives-scan

Looking closely at the thing the user named is half the job. The other half is asking what
else does that job, before a day goes into the first candidate. 2026-11-02: Strata got a 64 GB
download and a day-long bench; Avalon (same model, faster, better quantization) was 12th on a
single `gh search repos` sorted by stars, and nobody ran it.

The alternatives scan comes first, before you look closely at the named thing.

## The move, in order

1. **Goal and use cases.** One line each, from the user's own words, then memory
   (`memory_search` for the subject and the project), then their stated goals. Name what they
   want done with it: "run a coding agent locally, offline, on a 12 GB GPU with 46 GB RAM".
   Name the hard constraints (hardware, OS, licence, offline, privacy, budget). If the goal is
   unclear, say what you assumed.
2. **Category.** Strip the subject's name: "local inference engine for Qwen3.8-Flash-Next 125B
   on one consumer GPU". Write two or three phrasings, including one a level up ("run a strong
   coding model locally"), because the best alternative may not be the same kind of thing.
3. **Search, every source, every time:**
   - `python3 $STACK_ROOT/features/prompt-triggers/alternatives_scan.py search "<phrasing>"`
     for each phrasing (GitHub by stars).
   - WebSearch: "<subject> alternative", "<category> 2026", "<subject> vs". Comparisons and
     forum threads name rivals the GitHub search misses.
   - What's already here, before pricing any download: `memory_search`, `scout/map.md`,
     installed tools, and the local model and container inventory: `ls /opt/models/gguf`,
     `ollama list`, `~/.cache/huggingface/hub`, `docker ps -a`, `dcup list`, and the
     `docker/*/compose.yaml` model paths. A candidate already on disk (2026-11-03: Heretic
     already served Qwen3.6-35B-A3B and the scan priced it as a 15–20 GB download) changes the
     cheapest test. Note in its row which variant is local (quant, abliterated, context).
   - The subject's own README and issues: credits, "inspired by", "faster than X" tables.
4. **Read before you rank.** For the top 3–5 candidates, read the README or docs yourself
   (`gh api repos/<o>/<r>/readme`). Search summaries invent and conflate; their numbers are leads.
5. **Table.** At least 3 rows besides the subject: name, what it is, stars/updated/licence,
   fits the constraints?, why it could be worlds better, why worse. Mark every number as
   "their benchmark", "user report" or "measured here".
6. **Verdict.** A `## Verdict` section: the best fit for the goal (it may be the subject, or
   "nothing yet"), the one to test first and the cheapest test, and what would change the
   answer. A level-up alternative that beats the whole category says so plainly.
7. **Record.** Save the report under `review/alternatives/<date>-<slug>.md` in the Refinery
   repo, then:
   `python3 $STACK_ROOT/features/prompt-triggers/alternatives_scan.py record --subject <name>
   --category "<category>" --covers "<subject>,<cand1>,<owner/repo>,<model-repo>,..." --report <path>`.
   `--covers` lists every specific name a later download of any of these would contain (repo,
   model repo, image). Generic words ("qwen", "llama", "engine") don't count. The download gate
   accepts a download only when a recorded scan from the last 14 days covers it.

Then go back to what the user asked about the subject, with the alternatives in view.

## Quick reference

| You catch yourself… | Instead |
|---|---|
| Benchmarking the named tool before searching | Scan first; the bench may belong to another candidate |
| Searching only the subject's name | Search the category without the name, and one level up |
| Trusting a search summary's numbers | Read the candidate's README; label each number's source |
| Pricing a test as "one download" | Check the local model and container inventory first; it may already be here |
| "Not found anywhere" after a local search | Local is one source of four; run the web and GitHub searches |
| Prefixing ALT_SCAN_SKIP to get past the gate | Only when it truly isn't an adoption (your own repo, a reinstall); say why |

## Limits

Stars measure attention, not fitness. A 200-star project can beat a 40k-star one on your
hardware. The table says what fits the stated goal; the user's goal decides.

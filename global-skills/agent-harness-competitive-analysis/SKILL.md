
---
name: agent-harness-competitive-analysis
description: Structured competitive analysis of an AI agent harness or framework — maps the product against direct/indirect competitors, produces a comparison table, and identifies uncontested advantages
---

## When to use

When the user asks for a competitive analysis, "how do we compare to X", or "who else is doing what we're doing" for an AI agent harness, personal Claude Code setup, or similar framework product.

## Workflow

### 1. Check MemPalace first
Search for any prior competitive analysis or feature-port work before starting:
mempalace_search("competitive analysis [product name]")
mempalace_search("[product name] vs [competitor]")
If prior work exists, start from it rather than re-doing it.

### 2. Orient on the subject product
Pull a structural digest of the repo you're analyzing:
jcodemunch: digest / get_repo_health / get_repo_map
Note: primary language mix, top-complexity symbols, key architectural modules, entry points.

### 3. Research competitors in parallel
Run web research alongside the digest pull. Look for:
- Direct competitors (same philosophy, same user type)
- Ecosystem players (community marketplaces, managed platform equivalents)
- "Same energy" personal projects that evolved publicly

### 4. Structure the analysis output

Use this skeleton — do not invent sections not supported by evidence:

## [Product] — Competitive Analysis

**TL;DR:** One sentence on who wins at what and why.

### What [Product] Actually Is
- Architecture pattern (e.g., modular install scripts, MCP-first, etc.)
- Key subsystems with one-line descriptions
- Primary language and rough scale (file count, symbol count)

### The Competitor Map

#### 1. [Closest Competitor] — [relationship label]
[Context: release date, traction, key philosophy sentence]

| Dimension | [Competitor] | [Product] |
|---|---|---|
| [Key axis 1] | ... | ... |
| [Key axis 2] | ... | ... |
...

**Where [Product] is stronger:** ...
**Where [Competitor] is stronger:** ...

#### 2. [Next competitor] — [relationship label]
...

### Where [Product] Has No Real Competition
Numbered list of moats — specific, evidence-backed, not marketing copy.

### 5. Key dimensions to compare (pick what applies)

- Skill/workflow creation (manual vs. automatic, approval-gated vs. auto-commit)
- Memory architecture (layers, storage backend, curated vs. auto)
- Retrieval stack (generic embeddings vs. purpose-built per modality)
- Evaluation/quality loop (dedicated vs. none)
- Self-improvement mechanism (intentional replay vs. passive trajectory capture)
- Setup friction (zero-to-running vs. high-investment bespoke)
- Portability (standard format vs. single-harness)
- Security posture (supply chain risk, isolation, disclosure controls)
- Target user (personal/one-person vs. team vs. general public)
- Data ownership (local vs. vendor-hosted state)

### 6. Save to MemPalace
After compiling:
mempalace_add_drawer(wing="project", room="competitive-intel", ...)
Include: key findings, date, competitor versions/star counts at time of analysis.

## Output rules

- Lead every competitor section with its **relationship label**: "Most Direct Competitor", "Bigger Ecosystem", "Closest in Spirit", "Official Platform"
- Comparison tables must be evidence-backed — no cells invented without a source
- "Where X has no real competition" section is required; it's the most actionable part
- Keep TL;DR to one sentence that names the core philosophical split

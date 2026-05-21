---
name: readme-sync
description: Audit a README against actual repo contents, identify undocumented features, and make targeted edits to bring docs in sync with what's actually installed/shipped.
---

## When to Use

When a README is suspected to be stale — new features exist that aren't documented, install steps are missing, or the file map no longer reflects the codebase.

Trigger phrases: "update the README", "README is out of date", "add X to the docs", "README missing Y".

## Steps

### 1. Check prior README work
Before opening a single file, search MemPalace for prior README work on this repo:
mempalace_search("README <project-name>")
Skip if prior hits are for a different project.

### 2. Read the current README and recent commits in parallel
- `Read README.md` (or wherever the primary doc lives)
- `git log --oneline -20` to see what landed since the README was last touched

### 3. Inventory what exists vs. what's documented
Run a targeted scan — look for feature directories, scripts, and config files that might be undocumented:
Glob("features/**")
Glob("scripts/**")
Glob("global-skills/**")  # or plugin dirs, hooks dirs, etc.
Compare the list against what's mentioned in the README's feature table, install steps, and file map.

### 4. Read undocumented feature files for accurate descriptions
For each gap found, read the relevant entry point (e.g., `features/foo/README.md`, `scripts/bar.sh` header) to get an accurate one-liner before writing anything.

### 5. Make three targeted edits — no more
Focus on the three sections that matter most:
1. **Feature table / "What's in the box"** — add missing rows
2. **Install steps** — add missing optional-feature install sections
3. **File map** — add missing paths

Do not rewrite prose that is still accurate. Targeted edits only.

### 6. Verify
Re-read the changed sections to confirm no accidental truncation or formatting break.

## Key Principles

- Never rewrite a section that is still accurate — only add what's missing.
- Read feature files before writing descriptions; don't guess from filenames.
- Three targeted edits is the ceiling; if more sections are broken, fix the worst three and note the rest.
- After edits, the README's file map, feature table, and install steps should all be consistent with each other.

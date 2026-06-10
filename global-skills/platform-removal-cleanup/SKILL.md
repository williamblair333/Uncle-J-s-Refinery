---
name: platform-removal-cleanup
description: "Use when dropping support for a platform (OS, runtime, environment) and need to scrub all artifacts: scripts, binaries, docs, template placeholders, config comments, and source code branches."
---

# Platform Removal Cleanup

Systematically remove all traces of a target platform from a codebase with verification passes at each stage.

## When to Use

- Dropping Windows, macOS, 32-bit, a legacy runtime, or any named OS/environment
- Need to delete platform-specific scripts and remove references from docs, configs, templates, and source
- Clean break — no backwards-compat shims, no dead branches

## Workflow

### 1. Survey first

Grep broadly before touching anything:

```bash
grep -r "windows\|\.ps1\|powershell\|os\.name.*nt" --include="*.{md,sh,py,json,toml}" -l
```

Group hits into two buckets:
- **Delete** — files that exist only for the target platform (scripts, binaries, platform-only libs)
- **Edit** — shared files that reference the platform (docs, configs, templates, source)

### 2. Delete platform-only files first

```bash
git rm path/to/install.ps1 path/to/lib/helpers.ps1 ...
```

Commit or stage before editing — a clean diff makes the edits easier to review.

### 3. Update docs (README, PRD, CHANGELOG, feature READMEs)

For each doc:
- Remove platform-specific install/uninstall sections
- Strip the platform from goals, requirements, and file maps
- Clean iteration logs that reference the platform

Historical planning archives (frozen specs) can stay — flag them as frozen, don't edit.

### 4. Update configs and templates

- JSON/YAML: remove platform-specific keys and `_comment` fields
- `.json.tmpl` / template files: remove platform conditionals and placeholder tokens (e.g., `{{EXE}}`)
- Check rendered outputs match their templates

### 5. Simplify source code

For files that had platform guards:

```python
# Before
if os.name == "nt":
    ...windows path...
else:
    ...linux path...

# After — collapse to the surviving path
...linux path...
```

Strip platform imports, conditional branches, and cross-reference comments (e.g., `# see also install.ps1`).

### 6. Verify — grep for stragglers

```bash
grep -ri "windows\|\.ps1\|powershell" --include="*.{md,sh,py,json,toml}" -l
```

Review each hit:
- **Live docs/configs** → edit
- **Historical/frozen archives** → leave or note as frozen
- **Git history** → ignore (expected)

### 7. Final template/rendered-output sync check

If templates generate output files, confirm rendered outputs were also updated to match.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Editing docs before deleting scripts | Delete first — simplifies grep results |
| Missing template source files while updating rendered outputs | Always check `.tmpl`/source alongside rendered JSON/YAML |
| Cleaning historical planning archives | Mark as frozen; don't edit |
| Missing cross-reference comments in shell scripts | `grep -r "ps1\|\.ps1"` after main cleanup |
| Forgetting `_comment` keys in JSON templates | Search `_comment` separately |

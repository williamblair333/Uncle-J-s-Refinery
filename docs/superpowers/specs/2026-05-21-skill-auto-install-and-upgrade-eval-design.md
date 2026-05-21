# Design: Skill Auto-Install & Post-Upgrade Evaluation

*Date: 2026-05-21*

## Problem

Two automation gaps:

1. **Skill auto-install**: When a new skill is added to `global-skills/`, `auto-maintain.sh` already commits it to git nightly, but does **not** symlink it into `~/.claude/skills/`. The symlink step only lives in `install-reliability.sh`, which has a hardcoded skill name list — any new skill is invisible to Claude until a human runs the installer manually.

2. **Post-upgrade evaluation**: After a package upgrade, `auto-maintain.sh` Part B only checks for new jcodemunch tools and only updates `CLAUDE.md` routing. It does not cover mempalace, jdatamunch, or jdocmunch upgrades, and does not detect or act on breaking changes (e.g., mempalace KG tools rejecting partial dates in a recent upgrade).

## Scope

Two changes to existing files. No new files created.

- `install-reliability.sh` — replace hardcoded skill list with dynamic scan
- `scripts/auto-maintain.sh` — extend Part B and Part C

---

## Section 1: Skill Auto-Install

### install-reliability.sh

Replace the hardcoded `for skill in prior-art-check judge outcomes ...` loop (line ~29) with a dynamic scan of the `global-skills/` directory:

```bash
for src in "$STACK_ROOT/global-skills"/*/; do
    [ -d "$src" ] || continue
    skill_name=$(basename "$src")
    dst="$CLAUDE_DIR/skills/$skill_name"
    if [ -L "$dst" ] && [ "$(readlink -f "$dst")" = "$(readlink -f "$src")" ]; then
        ok "skill already linked: $skill_name"
        continue
    fi
    rm -rf "$dst"
    ln -sfn "$src" "$dst"
    ok "skill installed: $skill_name"
done
```

Any directory under `global-skills/` is treated as a skill. No list to maintain.

### auto-maintain.sh Part C

After the existing `git commit` that lands new skills, immediately run a symlink pass over all of `global-skills/`:

```bash
# After git -C "$PROJ_ROOT" commit ...
CLAUDE_DIR="${CLAUDE_HOME:-$HOME/.claude}"
mkdir -p "$CLAUDE_DIR/skills"
for src in "$PROJ_ROOT/global-skills"/*/; do
    [ -d "$src" ] || continue
    skill_name=$(basename "$src")
    dst="$CLAUDE_DIR/skills/$skill_name"
    if [ ! -L "$dst" ] || [ "$(readlink -f "$dst")" != "$(readlink -f "$src")" ]; then
        rm -rf "$dst"
        ln -sfn "$src" "$dst"
        info "Symlinked skill: $skill_name"
    fi
done
```

Skills are live before the next Claude session opens. The existing end-of-run Telegram notification already reports committed skills — no extra alert needed.

---

## Section 2: Post-Upgrade Evaluation

### auto-maintain.sh Part B (extended)

Extend from jcodemunch-only to all 4 packages (`jcodemunch-mcp`, `jdatamunch-mcp`, `jdocmunch-mcp`, `mempalace`), add breaking-change detection, and route through Claude for HANDOFF.md notes and CLAUDE.md routing updates.

#### Step 1: Capture pre-upgrade SHAs

Before calling `uv lock`, record the current SHA for every package queued for upgrade:

```bash
declare -A OLD_SHAS
for pkg in "${PACKAGES_TO_UPGRADE[@]}"; do
    OLD_SHAS[$pkg]=$(parse_lock_sha "$pkg")
done
```

#### Step 2: Fetch commit log after upgrade

After a successful `uv lock && uv sync`, for each upgraded package:

```bash
for pkg in "${PACKAGES_TO_UPGRADE[@]}"; do
    old_sha="${OLD_SHAS[$pkg]}"
    new_sha=$(parse_lock_sha "$pkg")
    [[ "$old_sha" == "$new_sha" || "$old_sha" == "?" ]] && continue

    commits=$(_gh_curl \
        "https://api.github.com/repos/${GITHUB[$pkg]}/compare/${old_sha}...${new_sha}" \
        | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for c in d.get('commits', []):
        print(c['commit']['message'].split('\n')[0])
except Exception:
    pass
" 2>/dev/null || true)

    # steps 3 and 4 execute here (breaking change grep + claude -p)
done
```

#### Step 3: Breaking change detection

Grep commit messages for risk keywords:

```bash
breaking=$(echo "$commits" | grep -iE \
    'breaking|BREAKING CHANGE|deprecated|removed|incompatible' || true)
```

If `$breaking` is non-empty, the package is flagged.

#### Step 4: Claude evaluation

One `claude -p` call per upgraded package. The prompt includes:
- Package name and SHA range
- Full commit log (one subject line per commit)
- Breaking changes highlighted (if any)
- Instruction to update `CLAUDE.md` routing if new tools require it
- Instruction to append a dated note to `HANDOFF.md` under "What happened" if breaking changes exist
- Instruction to touch nothing else

For jcodemunch specifically, the existing `jcodemunch-mcp claude-md --format append` tool detection still runs first; its output is included in the Claude prompt so Claude can incorporate it into the routing update in one pass.

#### Step 5: Telegram summary

The existing end-of-run Telegram message is extended to include:
- Which packages upgraded
- Whether breaking changes were detected per package
- One-line summary of what Claude noted (extracted from Claude's response)

#### Example: mempalace KG partial-date breaking change

With this design, the nightly flow would have been:
1. `commits_behind mempalace` → 16 → queued for upgrade
2. Pre-upgrade SHA captured
3. Upgrade runs
4. Commit log fetched; grep finds `"breaking"` in the KG date validation commit
5. Claude receives commit log + breaking change highlight + current mempalace CLAUDE.md section
6. Claude appends to HANDOFF.md: *"2026-05-21 — mempalace upgraded: KG tools (`mempalace_kg_add`, `mempalace_kg_query`) now reject partial dates like '2026-05'; use full YYYY-MM-DD."*
7. Telegram: `auto-maintain: upgraded mempalace. ⚠️ breaking change detected — see HANDOFF.md.`

---

## Error handling

- GitHub API failures during commit log fetch: log warning, skip evaluation for that package (non-fatal)
- Claude evaluation failure: log warning, breaking change still noted in Telegram without HANDOFF note
- Symlink step failure: log warning, non-fatal (skill is committed, just not yet linked)
- All exits remain 0 (cron must not fail loudly)

## Files changed

| File | Change |
|------|--------|
| `install-reliability.sh` | Replace hardcoded skill loop with dynamic `global-skills/` scan |
| `scripts/auto-maintain.sh` | Part B: pre-upgrade SHA capture, commit log fetch, breaking change grep, extended Claude prompt; Part C: symlink step after commit |

## Out of scope

- Telegram alert for individual skill installs (existing end-of-run message covers it)
- A separate human review gate for CLAUDE.md edits — Claude auto-patches all 4 packages using the same pattern currently used for jcodemunch; this is consistent, not a regression
- Any new files or scripts

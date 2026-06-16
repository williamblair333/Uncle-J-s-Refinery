# `install.sh --update` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `./install.sh --update` that pulls the latest repo changes and re-runs only the install sections affected by what changed — no manual `git pull` + guessing what to re-run.

**Architecture:** `--update` does a `git fetch` + SHA compare, pulls if behind, then uses `exec "$SCRIPT"` to replace the process with the freshly-pulled version of itself (re-exec pattern). The re-exec'd instance detects which files changed via `git diff ORIG_HEAD HEAD` and runs only the relevant install sections. A `SELF_UPDATED=1` env-var guard prevents infinite re-exec loops. Section-detection logic lives in `lib/install-update.sh` (sourced by `install.sh`) so it can be tested in isolation.

**Tech Stack:** bash, git, Python pytest (subprocess), existing `lib/feature-helpers.sh` pattern.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `lib/install-update.sh` | `detect_changed_sections()` — maps changed files → section names |
| Modify | `install.sh` | Add `--update` flag, source the helper, self-update block, selective-run block |
| Create | `tests/test_install_update.py` | pytest tests for section detection + guard behavior |
| Modify | `.github/workflows/ci.yml` | Add `test-install-update` job |

---

## Section Map (what `detect_changed_sections` returns)

| Changed files (regex) | Section returned |
|-----------------------|-----------------|
| `^(pyproject\.toml\|uv\.lock)$` | `uv_sync` |
| `^(global-skills/\|global-agents/\|install-reliability\.sh)` | `skills` |
| `^mcp-clients/` | `mcp_templates` |
| `\.md$` | `jdocmunch` |
| `^install\.sh$` | `full` ← triggers full re-install |

`full` takes precedence: if `install.sh` itself changed, drop `--update` and re-exec to run the entire installer unmodified.

---

## Task 1: Create `lib/install-update.sh` with `detect_changed_sections()`

**Files:**
- Create: `lib/install-update.sh`

- [ ] **Step 1: Create the file**

```bash
#!/usr/bin/env bash
# lib/install-update.sh — section-detection helpers for install.sh --update.
# Sourced by install.sh; functions here must not depend on install.sh globals.

# detect_changed_sections CHANGED_FILES_STRING
#
# Reads newline-separated changed file paths from $1.
# Prints section names (one per line) that need to run.
# Caller is responsible for deduplication if called multiple times.
#
# Section names:
#   uv_sync       pyproject.toml or uv.lock changed
#   skills        global-skills/, global-agents/, or install-reliability.sh changed
#   mcp_templates mcp-clients/ template changed
#   jdocmunch     any .md file changed
#   full          install.sh itself changed (caller should run full install)
detect_changed_sections() {
    local changed="$1"
    local -a sections=()
    echo "$changed" | grep -qE '^(pyproject\.toml|uv\.lock)$'                           && sections+=("uv_sync")
    echo "$changed" | grep -qE '^(global-skills/|global-agents/|install-reliability\.sh)' && sections+=("skills")
    echo "$changed" | grep -qE '^mcp-clients/'                                            && sections+=("mcp_templates")
    echo "$changed" | grep -qE '\.md$'                                                    && sections+=("jdocmunch")
    echo "$changed" | grep -qE '^install\.sh$'                                            && sections+=("full")
    printf '%s\n' "${sections[@]}"
}
```

- [ ] **Step 2: Verify syntax**

```bash
bash -n lib/install-update.sh && echo "OK"
```
Expected: `OK`

---

## Task 2: Write failing tests

**Files:**
- Create: `tests/test_install_update.py`

- [ ] **Step 1: Write the test file**

```python
"""Tests for lib/install-update.sh detect_changed_sections() and install.sh --update guard."""
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
LIB = REPO_ROOT / "lib" / "install-update.sh"
INSTALL = REPO_ROOT / "install.sh"

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
}


def detect(changed: str) -> list[str]:
    """Call detect_changed_sections() via bash subprocess."""
    script = f"source {LIB} && detect_changed_sections '{changed}'"
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    return [l for l in r.stdout.splitlines() if l]


# ── detect_changed_sections unit tests ──────────────────────────────────────

def test_pyproject_toml_returns_uv_sync():
    assert detect("pyproject.toml") == ["uv_sync"]


def test_uv_lock_returns_uv_sync():
    assert detect("uv.lock") == ["uv_sync"]


def test_global_skills_returns_skills():
    assert detect("global-skills/my-skill/skill.md") == ["skills"]


def test_install_reliability_returns_skills():
    assert detect("install-reliability.sh") == ["skills"]


def test_mcp_clients_returns_mcp_templates():
    assert detect("mcp-clients/claude-desktop-config-fragment.json.tmpl") == ["mcp_templates"]


def test_md_change_returns_jdocmunch():
    assert detect("README.md") == ["jdocmunch"]


def test_install_sh_returns_full():
    assert detect("install.sh") == ["full"]


def test_multiple_changes_returns_multiple_sections():
    changed = "pyproject.toml\nglobal-skills/foo/skill.md"
    sections = detect(changed)
    assert "uv_sync" in sections
    assert "skills" in sections


def test_unrelated_file_returns_empty():
    sections = detect("scripts/auto-maintain.sh")
    assert sections == []


def test_install_sh_alongside_others_returns_full_plus_others():
    changed = "install.sh\npyproject.toml"
    sections = detect(changed)
    assert "full" in sections
    assert "uv_sync" in sections


# ── SELF_UPDATED guard test ──────────────────────────────────────────────────

def test_update_flag_with_self_updated_guard_skips_git_operations(tmp_path):
    """When SELF_UPDATED=1, --update must not attempt git fetch/pull."""
    # Create a minimal git repo so install.sh can source lib/feature-helpers.sh
    # but we intercept before any network call.
    # We just verify the script exits without calling git fetch.
    fake_git = tmp_path / "git"
    fake_git.write_text("#!/bin/sh\necho FAKE_GIT_CALLED: $* >&2\nexit 0\n")
    fake_git.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "SELF_UPDATED": "1",
    }
    result = subprocess.run(
        ["bash", str(INSTALL), "--update", "--non-interactive"],
        capture_output=True, text=True, env=env,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    # Script should NOT have called `git fetch` (guard short-circuits)
    assert "FAKE_GIT_CALLED: fetch" not in result.stderr
```

- [ ] **Step 2: Run tests to confirm they all fail (lib file doesn't exist yet)**

```bash
uv run pytest tests/test_install_update.py -v 2>&1 | head -30
```
Expected: errors like `FileNotFoundError` or `CalledProcessError` — the lib doesn't exist yet.

---

## Task 3: Make the unit tests pass

**Files:**
- `lib/install-update.sh` already created in Task 1

- [ ] **Step 1: Run the detect_changed_sections tests**

```bash
uv run pytest tests/test_install_update.py -v -k "not guard"
```
Expected: all 10 detect tests pass.

- [ ] **Step 2: Fix any failures**

Common failure: `grep -qE` with newlines in `$1`. If multi-line input fails, replace `echo "$changed"` with `printf '%s\n' "$changed"` — both are equivalent for this use. The test fixture uses `\n` literals; verify bash receives them as actual newlines via the single-quoted heredoc approach.

If `test_multiple_changes_returns_multiple_sections` fails, the issue is `$'pyproject.toml\nglobal-skills/foo/skill.md'` vs `"pyproject.toml\nglobal-skills/..."`. Fix the test to use `$'\n'` as separator:

```python
changed = "pyproject.toml" + "\n" + "global-skills/foo/skill.md"
```

- [ ] **Step 3: Run all tests except the guard test**

```bash
uv run pytest tests/test_install_update.py -v -k "not guard"
```
Expected: 10/10 pass.

---

## Task 4: Add the self-update block to `install.sh`

**Files:**
- Modify: `install.sh` (lines 1–28, the flag-parsing section)

- [ ] **Step 1: Read current flag-parsing block (lines 14–28)**

Confirm it looks like:
```bash
set -euo pipefail
STACK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$STACK_ROOT"

AUTO_REGISTER=1
SKIP_OPTIONAL=0
NON_INTERACTIVE=0
for arg in "$@"; do
    case "$arg" in
        --auto-register)   AUTO_REGISTER=1 ;;
        --skip-optional)   SKIP_OPTIONAL=1 ;;
        --non-interactive) NON_INTERACTIVE=1 ;;
    esac
done
export NON_INTERACTIVE
```

- [ ] **Step 2: Edit `install.sh` — add `--update` flag + source the helper**

Replace the flag-parsing block (lines 14–28) with:

```bash
set -euo pipefail
STACK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$(readlink -f "$0")"
cd "$STACK_ROOT"

# Source section-detection helper (needed before arg parsing for --update)
# shellcheck source=lib/install-update.sh
source "$STACK_ROOT/lib/install-update.sh"

AUTO_REGISTER=1
SKIP_OPTIONAL=0
NON_INTERACTIVE=0
UPDATE=0
SELF_UPDATED="${SELF_UPDATED:-0}"
for arg in "$@"; do
    case "$arg" in
        --auto-register)   AUTO_REGISTER=1 ;;
        --skip-optional)   SKIP_OPTIONAL=1 ;;
        --non-interactive) NON_INTERACTIVE=1 ;;
        --update)          UPDATE=1 ;;
    esac
done
export NON_INTERACTIVE
```

- [ ] **Step 3: Add the self-update block** immediately after the `export NON_INTERACTIVE` line:

```bash
# ── Self-update (--update flag) ──────────────────────────────────────────────
# Phase A: pull new code and re-exec with the freshly-pulled script.
#   SELF_UPDATED=1 guard prevents re-exec loops.
# Phase B (after re-exec): detect what changed and run selective sections.
if [[ "$UPDATE" == "1" && "$SELF_UPDATED" != "1" ]]; then
    step "Checking for updates"
    git fetch --quiet origin main
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main)
    if [[ "$LOCAL" == "$REMOTE" ]]; then
        ok "Already at HEAD — nothing to pull"
        # Fall through: still run install normally (user may want a clean re-run)
        UPDATE=0
    else
        ok "Updates found ($(git rev-parse --short HEAD)..$(git rev-parse --short origin/main))"
        if ! git pull --ff-only --quiet origin main; then
            warn "git pull failed — resolve conflicts then re-run"
            exit 1
        fi
        ok "Pulled to $(git rev-parse --short HEAD)"
        export SELF_UPDATED=1
        exec "$SCRIPT" "$@"
        # exec never returns
    fi
fi
```

- [ ] **Step 4: Verify syntax**

```bash
bash -n install.sh && echo "OK"
```
Expected: `OK`

- [ ] **Step 5: Run the guard test**

```bash
uv run pytest tests/test_install_update.py::test_update_flag_with_self_updated_guard_skips_git_operations -v
```
Expected: PASS.

---

## Task 5: Add selective-section running (Phase B)

This block runs after the re-exec — `SELF_UPDATED=1` and `UPDATE=1` are both true.

**Files:**
- Modify: `install.sh` — add Phase B block immediately after the Phase A block from Task 4

- [ ] **Step 1: Add the Phase B block**

Insert immediately after the closing `fi` of the Phase A block:

```bash
# Phase B: selective section run (post re-exec)
if [[ "$UPDATE" == "1" && "$SELF_UPDATED" == "1" ]]; then
    CHANGED=$(git diff ORIG_HEAD HEAD --name-only 2>/dev/null || echo "")
    if [[ -z "$CHANGED" ]]; then
        ok "No file changes detected after pull — nothing to do"
        exit 0
    fi
    SECTIONS=$(detect_changed_sections "$CHANGED")

    # If install.sh itself changed, run the full installer without --update
    if echo "$SECTIONS" | grep -q "^full$"; then
        step "install.sh changed — running full install"
        ARGS_NO_UPDATE=()
        for arg in "$@"; do [[ "$arg" != "--update" ]] && ARGS_NO_UPDATE+=("$arg"); done
        exec "$SCRIPT" "${ARGS_NO_UPDATE[@]}"
    fi

    step "Selective update ($(echo "$SECTIONS" | tr '\n' ' '))"

    if echo "$SECTIONS" | grep -q "^uv_sync$"; then
        step "Syncing Python dependencies (pyproject.toml/uv.lock changed)"
        uv sync --inexact
        ok "Python stack updated"
    fi

    if echo "$SECTIONS" | grep -q "^skills$"; then
        step "Updating skills (global-skills/ changed)"
        bash "$STACK_ROOT/install-reliability.sh" --non-interactive
        ok "Skills updated"
    fi

    if echo "$SECTIONS" | grep -q "^mcp_templates$"; then
        step "Re-rendering mcp-clients/*.json templates"
        MCP_DIR="$STACK_ROOT/mcp-clients"
        VENV_BIN="$STACK_ROOT/.venv/bin"
        for tmpl in "$MCP_DIR"/*.json.tmpl; do
            out="${tmpl%.tmpl}"
            sed -e "s|{{STACK_VENV_BIN}}|$VENV_BIN|g" -e "s|{{EXE}}||g" "$tmpl" > "$out"
            ok "rendered $(basename "$out")"
        done
    fi

    if echo "$SECTIONS" | grep -q "^jdocmunch$"; then
        step "Re-indexing docs (markdown changed)"
        VENV_BIN="$STACK_ROOT/.venv/bin"
        if [ -x "$VENV_BIN/jdocmunch-mcp" ]; then
            "$VENV_BIN/jdocmunch-mcp" index-local --path "$STACK_ROOT" \
                >"$STACK_ROOT/.install-jdm-index.log" 2>&1 && ok "jdocmunch re-indexed" || \
                warn "jdocmunch index failed (see .install-jdm-index.log)"
        fi
    fi

    step "Update complete"
    printf '\nRun: bash healthcheck.sh   to verify everything is OK\n\n'
    exit 0
fi
```

- [ ] **Step 2: Verify syntax**

```bash
bash -n install.sh && echo "OK"
```
Expected: `OK`

- [ ] **Step 3: Manual smoke test (no network needed — SELF_UPDATED guard fires)**

```bash
SELF_UPDATED=1 bash install.sh --update --non-interactive 2>&1 | head -5
```
Expected: output containing "No file changes detected" or "Selective update" (depending on whether ORIG_HEAD exists in this repo). It should NOT run the full install.

---

## Task 6: Update `install.sh` usage comment

**Files:**
- Modify: `install.sh` lines 1–12 (the header comment)

- [ ] **Step 1: Update the usage block**

Change:
```bash
# Usage:
#   ./install.sh                    # install stack + register MCP servers + run healthcheck
#   ./install.sh --skip-optional    # skip MotherDuck warm-cache
#   ./install.sh --non-interactive  # skip all optional-feature prompts (CI/automation)
```

To:
```bash
# Usage:
#   ./install.sh                    # install stack + register MCP servers + run healthcheck
#   ./install.sh --update           # git pull + re-run only changed sections (idempotent)
#   ./install.sh --skip-optional    # skip MotherDuck warm-cache
#   ./install.sh --non-interactive  # skip all optional-feature prompts (CI/automation)
#
# --update flow: fetches origin/main, pulls if behind, re-execs the new script,
#   then runs only the sections affected by what changed (skills, deps, docs, etc.).
#   If install.sh itself changed, runs the full install automatically.
```

- [ ] **Step 2: Verify syntax**

```bash
bash -n install.sh && echo "OK"
```

---

## Task 7: Add CI job

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Append a new job to `ci.yml`**

Add after the existing `test-audit` job:

```yaml
  # ── 7. install --update unit tests ───────────────────────────────────────
  test-install-update:
    name: install --update section detection tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Add ~/.local/bin to PATH
        run: echo "$HOME/.local/bin" >> "$GITHUB_PATH"

      - name: Install dev dependencies
        run: uv sync --inexact --only-group dev

      - name: pytest tests/test_install_update.py (unit tests only)
        run: uv run pytest tests/test_install_update.py -v -k "not guard"
```

Note: the guard test (`test_update_flag_with_self_updated_guard_skips_git_operations`) is excluded from CI because it requires a full `install.sh` run environment (uv, claude CLI, etc.) that doesn't exist in the CI image. The unit tests for `detect_changed_sections` run fine without any of that.

- [ ] **Step 2: Validate CI YAML syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "OK"
```
Expected: `OK`

---

## Task 8: Commit

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest tests/test_install_update.py -v -k "not guard"
bash -n install.sh lib/install-update.sh
```
Expected: all tests pass, both syntax checks OK.

- [ ] **Step 2: Run shellcheck**

```bash
shellcheck --severity=error --exclude=SC1091 install.sh lib/install-update.sh
```
Fix any errors before committing.

- [ ] **Step 3: Stage and commit**

```bash
git add install.sh lib/install-update.sh tests/test_install_update.py .github/workflows/ci.yml
git commit -m "feat(install): add --update flag with re-exec + selective section running"
```

---

## Self-Review

**Spec coverage:**
- ✅ `./install.sh --update` pulls latest and re-runs → Task 4 (Phase A) + Task 5 (Phase B)
- ✅ Re-exec pattern with `SELF_UPDATED=1` guard → Task 4
- ✅ Selective section detection (`detect_changed_sections`) → Task 1 + Task 3
- ✅ `install.sh` itself changed → full re-install → Task 5 (`full` section case)
- ✅ Already at HEAD → `ok "Already at HEAD"` then falls through → Task 4
- ✅ Tests for all detection cases → Task 2
- ✅ CI job → Task 7

**Placeholder scan:** None found. All code blocks are complete.

**Type consistency:** `SECTIONS` string, `detect_changed_sections` function name, `CHANGED` variable — consistent across Task 1, Task 5, and test file.

**One edge case to verify:** `git diff ORIG_HEAD HEAD` in Phase B — `ORIG_HEAD` is set by `git pull` and persists until the next merge/reset. In the re-exec'd instance it's still valid. If someone runs `install.sh --update --non-interactive` and the pull brought no actual file changes (e.g., a merge commit with no content diff), `CHANGED` will be empty and the script exits cleanly with "No file changes detected."

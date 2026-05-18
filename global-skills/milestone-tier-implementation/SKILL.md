
---
name: milestone-tier-implementation
description: Implement one or more new library tiers in a milestone-based Python project — read handoff, match existing patterns, implement, wire up, test, then update all docs atomically.
---

## When to use

When a handoff doc identifies unimplemented tiers and you need to bring them to parity with existing tiers: same file structure, same test harness, same `__init__.py` / test-runner wiring, and synchronized docs (README, CHANGELOG, HANDOFF).

## Steps

### 1. Verify handoff claims against live source
Before repeating anything from a handoff doc, cross-check it:
- Confirm passing test count: `python -m pytest --tb=no -q`
- Confirm which tier files exist: `ls partikus/tier*.py`
- Confirm which test files exist: `ls tests/test_tier*.py`
- Flag any handoff claims that are already resolved.

### 2. Read one existing tier + its test for pattern reference
# Read a mid-complexity tier (e.g. tier06) and its test file
# Note: class name, __all__, function signatures, docstring style

### 3. Implement each new tier file
- Match file naming: `partikus/tierNN_<name>.py`
- Define an `__all__` list
- Mirror the class/function pattern from existing tiers
- Stub complex subsections with `raise NotImplementedError` or minimal skeletons if full spec isn't available

### 4. Wire into `__init__.py`
# Add import and extend __all__
from .tierNN_name import ClassName
__all__ += ['ClassName']

### 5. Write test file
- Match naming: `tests/test_tierNN.py`
- Mirror test class structure from an existing test file
- Cover: instantiation, key methods, edge cases, error paths

### 6. Wire into `run_tests.py`
import tests.test_tierNN
# add to test runner list

### 7. Run full test suite — fix until 0 failures
python tests/run_tests.py
# or: python -m pytest

### 8. Update docs atomically (only after green)
In order:
1. **CHANGELOG.md** — add entry under new milestone heading; update footer links
2. **README.md** — update badge, tier reference sections, project structure tree, test coverage table, roadmap
3. **HANDOFF.md** — update implemented tier list, test count, quick sanity check section, module list, final status line

### 9. Final verification run
python -m pytest --tb=short -q
Confirm count matches what you wrote in the docs.

### 10. Update memory
Save new project state (milestone complete, test count, next milestone target) to the persistent memory index.

## Key invariants
- Never update docs before tests are green.
- Stub counts must match: every new tier file needs a corresponding test file.
- `__all__` in `__init__.py` must stay in sync with tier files.
- HANDOFF.md is the source of truth for "what's next" — update it last.

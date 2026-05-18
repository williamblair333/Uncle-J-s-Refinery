
---
name: freecad-parametric-toolkit-build
description: Build a FreeCAD parametric CAD toolkit tier by tier — probe APIs first, implement modules, run tests with freecadcmd, fix stdout capture issues.

---

## When to use

When implementing a multi-tier FreeCAD Python toolkit from a spec/handoff doc, where each tier builds on the previous and tests must run headlessly via `freecadcmd`.

## Key steps demonstrated

### 1. Probe FreeCAD APIs before writing code
freecadcmd -c "import Part; ..."
Confirm specific API calls (e.g. `Part.makeEllipse` vs `Part.Ellipse(...)`) before committing to an implementation. Saves rewrites.

### 2. Module structure
partikus/
  core/anchors.py          # anchor name constants
  core/shape_wrapper.py    # PartikusShape wrapping Part.Shape
  core/transforms.py       # rotation/placement helpers
  core/document.py         # add_shape() to push into FreeCAD docs
  tier00_foundations.py    # coordinate/axis/plane constants
  tier01_primitives.py     # 9 raw primitives, all centered at origin
  tier09_boolean.py        # union/difference/intersection
  tier10_modifiers.py      # fillet/chamfer/shell/offset
  tier11_patterns.py       # linear_array/polar_array/mirror
  tier14_assembly.py       # translate/rotate/attach/stack_on
  gui/auto_dialog.py       # introspect signatures → PySide2 dialogs
  gui/workbench.py         # FreeCAD workbench + toolbar

### 3. freecadcmd stdout capture gotcha
`freecadcmd` swallows `print()` and does **not** set `__name__ == "__main__"`. Two fixes:
- Use `FreeCAD.Console.PrintMessage(...)` instead of `print()`
- Or write test output to stderr: `import sys; print(..., file=sys.stderr)`
- The `if __name__ == "__main__":` guard will never fire — call the runner unconditionally or use a direct function call

### 4. Design decisions (from this session)
- **Composition over subclassing**: hold `Part.Shape`, don't subclass it
- **Eager anchor computation**: simpler, no serialization complexity
- **Non-parametric**: use `Part::Feature`, not `Part::FeaturePython` (no history tree)
- **All shapes bounding-box centered at origin**: makes `attach()` math predictable

### 5. API correction caught in testing
# Wrong:
Part.makeEllipse(center, major_radius, minor_radius)
# Correct:
Part.Ellipse(center, major_radius, minor_radius).toShape()

### 6. Tier build order (maximum payoff)
1. Tier 10 (modifiers) — unlocks `rounded_box` and real parts
2. Tier 11 (patterns) — short, immediately useful
3. Tier 2 (enhanced primitives) — mostly T1 + T10 wrappers
4. Tier 3 + Tier 12 together (profiles → extrude/revolve/sweep/loft)

## Test runner pattern
# tests/run_tests.py — works with freecadcmd
import FreeCAD, sys
results = run_all_tests()
FreeCAD.Console.PrintMessage(f"{results.passed}/{results.total} passing\n")
if results.failed:
    sys.exit(1)

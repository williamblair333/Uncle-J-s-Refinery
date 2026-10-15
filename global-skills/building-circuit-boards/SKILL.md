---
name: building-circuit-boards
description: Use when asked to design, make, revise, or order a printed circuit board (PCB), produce Gerbers or a fab zip for JLCPCB/PCBWay, or create a KiCad board or schematic — including "just get me the zip", rushed orders, and small changes to an existing board.
---

# Building circuit boards

## Overview

A board is done when the circuit is **simulated, generated from one source of
truth, checked against its schematic pin by pin, reviewed, rendered with its
components, documented, and merged**. A fab zip on its own proves almost nothing:
swapped pins, wrong footprints and a wrong circuit all produce a perfectly valid zip.

**Violating the letter of the checklist is violating its spirit.**

## When to use

- A new board, or any change to an existing one (layout, part, label, net).
- Exporting Gerbers or a fab zip, even under deadline.
- Not for: breadboard-only builds with no PCB.

## The pipeline

If the repo has `docs/PCB-PIPELINE.md`, **follow it exactly**. It names that
repo's commands. In free-energy, the whole board is:

```
/usr/bin/python3 pcb/make_board.py <board>   # schematic → board → route → ERC/DRC/parity → fab/ (prints RESULT: PASS)
uv run pytest                                # pin-by-pin netlist, KiCad-sim vs model, fab files, renders
```

Without a pipeline doc, the same stages apply. Build the tooling once rather
than hand-making one board:

1. **Simulate** the circuit (ngspice) and pin its predictions in tests.
2. **One source of truth** (`circuit.py`): parts, pin → net, and simulation
   models. Generate both the schematic and the board from it. Never hand-edit
   both.
3. **Board:** place, then autoroute.
   - Silkscreen on the **front only**: reference plus what each part is, and
     polarity marks.
   - Connectors face the edge.
4. **Checks:**
   - ERC, plus DRC **with `--schematic-parity` at all severities**, all 0.
   - Tests compare netlists **in pin order**, so a set compare can't hide a
     swapped emitter and collector.
   - Run KiCad's own simulation of the schematic and compare it with the
     model.
5. **Look at** the renders with 3D models: top and angled.
6. **Independent review** by a fresh agent: nets, footprint pin semantics
   against datasheets, hole sizes, clearances.
7. **Docs, PR, merge.** Report the counts, the zip path and the render.

## Quick reference: what "done" requires

| Check | Pass condition |
|---|---|
| Schematic | Generated, ERC 0 |
| Board | 0 unrouted, DRC + parity 0 at all severities |
| Pins | Pin-order netlist test; a sabotage test (e.g. swap E/C) must fail it |
| Simulation | KiCad schematic sim within 10 % of the model |
| Visual | Renders show every component, no overlaps, front-only text |
| Review | Independent agent, findings fixed |
| Ship | Docs + PR merged + tests and lint green |

## Rationalizations: all mean "run the pipeline"

| Excuse | Reality |
|---|---|
| "Deadline: just get them the zip" | The pipeline takes about 2 minutes. A wrong board costs a re-order and a week. |
| "Skip the schematic, the board is simple" | Parity is the only check that the board is the circuit you meant. |
| "DRC passed, so it's right" | DRC checks geometry, not intent. A swapped pinout passes DRC. |
| "Hand-route it, it's 5 parts" | Then the routing is unchecked by the same flow. Use the pipeline. |
| "Docs/tests/PR are follow-ups" | Follow-ups don't happen. They're part of done. |
| "Warnings aren't errors" | Silk overlaps and net-name conflicts are real defects. Clear them or justify each one. |
| "3D models are cosmetic" | The 3D view caught connectors facing inward on the first board here. |

## Red flags: stop

- About to upload or hand over a zip without `RESULT: PASS` and a green
  `pytest`.
- About to edit a `.kicad_pcb` or `.kicad_sch` by hand.
- "I'll list the skipped items as follow-ups."
- A test compares nets as **sets**.

If you truly must hand files over early, label them **UNVERIFIED** and list
every unticked item. Then finish the pipeline before calling the board done.

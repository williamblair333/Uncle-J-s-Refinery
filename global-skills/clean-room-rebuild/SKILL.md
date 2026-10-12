---
name: clean-room-rebuild
description: Use when building original software that replicates the functionality of an existing app, including any use of REA (morluto/rea) to study a target, so the work stays a lawful clean-room reimplementation.
---

# Clean-Room Rebuild

Build original software that does what an existing product does, without copying
its code, assets, or protected expression. The legal protection comes from the
process actually being clean, documented as it happens. Nothing here hides or
launders copied material. If a step would require that, stop.

Reference model: the 2026 ArtCraft "Crafting Apps" Adobe alternatives were built
from public specifications and observed behavior, with no proprietary code reused.
They did not depend on decompiling. Follow that order: decompiling is the last
resort, used only for interoperability gaps.

## Roles (separate agents, separate sessions, separate project directories)

| Role | May see | May never see | Tools |
|---|---|---|---|
| Investigator | Target app, REA output, public docs | Implementation repo | REA MCP, browser, capture tools |
| Spec Scrubber | Investigator's draft spec | Raw REA output, binaries | Text only |
| Implementer | Scrubbed spec, public docs, public standards | Target binaries, decompiled code, REA output, Investigator notes | Compiler, tests. REA NOT registered. |
| Verifier | Original app (as a black box), new app | Decompiled code | Test harness |

Rules:
- The Implementer's project must not have REA registered as an MCP server. Check its MCP config before every session.
- No shared scratch directories, chat history, or memory between Investigator and Implementer.
- The only artifact crossing the wall is the scrubbed spec in `spec/`.
- A human gatekeeper approves each spec change before it crosses.

## Phase 0: Authorization gate (stop if any item fails)

- [ ] A lawfully obtained, licensed copy of the target is owned.
- [ ] The target's EULA/ToS has been read. Record whether it prohibits reverse engineering, decompiling, or benchmarking.
- [ ] If it prohibits reverse engineering: Investigator is limited to Tiers 1 and 2 below. Static analysis requires a lawyer's sign-off recorded in `provenance/authorization.md`.
- [ ] No step involves bypassing DRM, license checks, activation, encryption, anti-tamper, or anti-debugging. Hard stop. No exceptions for "research."
- [ ] Analysis tools (Hopper, IDA, JEB) are properly licensed. Demo/trial terms are respected.
- [ ] Patent search done for the core features (Google Patents, USPTO). Clean-room does not protect against patents. Record findings and design-arounds.
- [ ] Jurisdiction noted. Interoperability exceptions differ by country; confirm with counsel before relying on one.

Record all of this in `provenance/authorization.md` with dates.

## Phase 1: Investigation (Investigator only)

Use the lowest tier that answers the question. Record which tier answered each item.

### Tier 1: Public sources
- Official docs, help pages, published file-format specs, API references, SDKs, standards (ISO, IETF RFCs, W3C), open-source readers/writers of the same format.
- Tutorials and public user knowledge of features and behavior.

### Tier 2: Black-box observation (preferred, matches the Adobe-clone method)
- Use the app; record inputs and outputs. Screenshot behavior to define function, not to copy the UI.
- File I/O: create files with known content, diff outputs to infer format fields.
- Network: HAR captures; REA can analyze saved captures.
- Process behavior: REA process capture (Linux/macOS) for terminal output, filesystem effects, exit states.
- Websites: REA browser analysis for structure, scripts, network observations.
- Hardware/USB devices: `usbmon` + Wireshark with the vendor software in a VM.

### Tier 3: Static analysis with REA (only if authorized in Phase 0)
- Install without client setup: `install.sh --no-setup`, or `npm install --global --prefix ~/.local rea-agents@<exact version>`.
- Do NOT let `rea setup` configure Claude Code. It writes REA into the top-level `mcpServers` of `~/.claude.json` (user scope) and its skills into `~/.claude/skills`, which puts REA in every project on the machine, the Implementer's included. If setup asks which clients to configure, deselect Claude Code. Configure the analysis provider with `rea doctor` only.
- Register REA in the Investigator project only, at local scope. Run this from inside `investigator-workspace/`:
  ```bash
  claude mcp add --scope local rea -- npx rea-agents mcp
  ```
  Local scope is stored under that directory's entry in `~/.claude.json`. It isn't committed, isn't shared, and isn't visible from any other directory. Don't use `--scope project`: it writes `.mcp.json` into the repo, where it can be copied or committed across the wall.
- Confirm: `claude mcp list` inside `investigator-workspace/` shows `rea`; run from any other directory, it must not. If REA was already registered at user scope, remove it first with `claude mcp remove --scope user rea` and delete the REA skills it added to `~/.claude/skills`.
- Then `rea doctor` to confirm the provider (Hopper, Ghidra, or IDA).
- Electron/JS: `rea analyze-javascript-application <path> --json` for modules, IPC, routes.
- .NET: static metadata and CIL inspection.
- Native: `rea analyze` / `rea decompile` for pseudocode on the specific function in question.
- Scope every query to one feature. Never decompile a whole app "to see what's there."
- Purpose of Tier 3: extract facts (formats, protocols, algorithms' math, constants required for compatibility), never structure or code.

### Investigator output: `investigation/notes/` (stays on the Investigator side forever)

## Phase 2: Write the functional spec (Investigator drafts)

One file per feature: `spec/<feature>.md`.

```
# Feature: <neutral functional name, not the product's name>
## Purpose
What the user accomplishes.
## Inputs
Types, ranges, units, file formats (field tables, byte offsets, endianness).
## Outputs
Exact observable results, with tolerances.
## Behavior
Numbered rules in plain language. Math as formulas.
## Edge cases
Observed behavior at limits, errors (described, not quoted).
## Interop requirements
Formats/protocols that must match exactly, and why.
## Conformance tests
Input -> expected output pairs, generated by running the original as a black box.
## Provenance
Tier used per rule, with a reference to the Investigator's evidence ID.
```

Allowed in the spec:
- Facts: format layouts, protocol messages, constants needed for compatibility, mathematical formulas, observed input/output pairs.

Forbidden in the spec:
- Any source code, pseudocode, or assembly, including "cleaned up" versions.
- Internal function, class, or variable names from the binary.
- Code structure: call graphs, module layout, control flow mirroring the original.
- Verbatim strings: UI text, error messages, help text, comments.
- Assets: icons, images, fonts, sounds, sample files, presets, templates, brushes, LUTs.
- Product names, logos, trademarks.

## Phase 3: Scrub (Spec Scrubber)

Run on every spec file before it crosses the wall:
1. Reject anything in the forbidden list above.
2. Flag any sentence that reads like translated code ("loop over X, if Y then call Z"). Rewrite as a behavior rule or an input/output requirement.
3. Confirm every rule has a provenance entry.
4. Confirm conformance tests are black-box (inputs and observed outputs only).
5. Human gatekeeper approves; commit to `spec/` with the approver's name.

## Phase 4: Implementation (Implementer)

- Start from an empty repo. Pre-flight: confirm no REA MCP registration (`claude mcp list` from the implementation directory must not show `rea`, and `~/.claude/skills` must hold no REA skills), no access to `investigation/`, no binaries of the target on the Implementer's machine/container.
- Implementer's project instructions state: "Build only from `spec/` and public sources. If the spec is insufficient, file a question in `spec/questions.md`. Never request decompiled output."
- Questions go back through the Investigator, who answers by updating the spec (scrubbed again).
- Choose architecture independently. Do not mirror the original's module layout even when described by behavior.
- Use parallel agents per feature, each reading only its spec file. Track which spec version each module was built from.
- Use openly licensed libraries; record licenses in `THIRD_PARTY.md`.

## Phase 5: Verification (Verifier)

- Run spec conformance tests against the new app.
- Differential testing: feed identical inputs to the original and the new app, compare outputs. This is black-box and allowed.
- File-format round-trip: open files saved by the original, re-save, compare render or data.
- Similarity audit before release: check the codebase for verbatim strings, assets, or symbol names from the target (grep against the Investigator's extracted strings list, run by the Investigator side, report pass/fail only).

## Phase 6: Product and release checklist

- [ ] Own name, own logo, own icons. No confusingly similar branding.
- [ ] UI: own layout and visual design. Copying menus, panels, and look closely increases trade dress and copyright risk; matching keyboard shortcuts is lower-risk but confirm with counsel.
- [ ] Compatibility claims phrased factually ("opens .xyz files"), no implied affiliation.
- [ ] Patent findings resolved or designed around.
- [ ] `provenance/` archived: authorization, investigation log index, spec history with approvals, Implementer session logs showing no wall crossings.
- [ ] Counsel review before commercial release.

## Directory layout

```
investigator-workspace/       # Investigator only
  investigation/notes/
  investigation/evidence/     # captures, REA outputs, screenshots
handoff/
  spec/                       # the only thing that crosses
  spec/questions.md
implementation/               # Implementer only, separate repo
provenance/
  authorization.md
  wall-log.md                 # every spec crossing: date, files, approver
```

## Red flags (stop and re-scope)

- Someone proposes giving the Implementer "just a snippet" of decompiled code.
- The spec contains pseudocode or names from the binary.
- The plan requires defeating a license check, DRM, or obfuscation.
- The goal is a drop-in replacement using the original's name or branding.
- The target's EULA forbids reverse engineering and there's no counsel sign-off for Tier 3.
- The project targets a single company's paid features to resell unchanged with its look and feel.

## Examples: when this skill applies

Will fire (the goal is a working replacement for something that already exists):
- "Build an open-source app that does what <paid photo editor> does." Tier 1 + 2; no REA.
- "Write a reader/writer for <app>'s undocumented project file format so we can migrate our data out." Tier 2 file diffing first; Tier 3 REA on the parser only if diffing can't resolve a field.
- "Our USB label printer's vendor app is Windows-only; write a Linux driver." Tier 2 `usbmon` captures; Tier 3 only for a command checksum you can't infer.
- "Replace a discontinued vendor tool our team still depends on." Tier 1 + 2; check the EULA first.
- "Make a self-hosted server compatible with <app>'s sync protocol." Tier 2 HAR captures; Tier 3 if the payload encoding is opaque.
- Any request to register REA, or run `rea analyze`/`rea decompile` on a third-party binary, as part of building something.

Might fire (decide at Phase 0):
- "Build something like <app>." If it only takes ideas, with no compatibility goal and no study of the target, the full wall is optional. Keep the Phase 6 branding and UI checklist.
- Exporting your own data from a closed app. Use the app's export or API first. If that fails, interop format work falls under this skill.
- Porting a game or tool whose engine is open but whose assets are proprietary. Never ship the assets; the rest is ordinary development.

Won't fire:
- Rewriting or porting your own code, or code under an open license that you comply with.
- Integrating with a documented public API or SDK.
- Malware analysis or security research where nothing is rebuilt. REA is fine there, and this process isn't needed.
- Cracking, keygens, DRM or license bypass. Refuse; no tier covers it.

## When decompiling is unnecessary (most cases)

Creative tools, productivity apps, and most UIs can be rebuilt from Tier 1 + Tier 2 alone. Reserve Tier 3 for: undocumented binary file formats, wire protocols, hardware command sets, and exact algorithms where output must match bit-for-bit for interoperability.

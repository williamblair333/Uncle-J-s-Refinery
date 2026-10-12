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
- The Implementer's account must have no access to REA, the target, or anything the Investigator wrote. "No access" means the OS stops it, not that the agent was told not to. See "Isolation" below.
- No shared scratch directories, chat history, or memory between Investigator and Implementer.
- The only artifact crossing the wall is the scrubbed spec in `spec/`.
- A human gatekeeper approves each spec change before it crosses, and copies it across by hand.

## Isolation (decide before the first REA call, Tier 2 or 3)

An agent can do anything its OS account can do. It can run any `rea` on the `PATH`, start REA with `npx`, and read every file that account can read. Separate Claude Code profiles or MCP scopes only change what a session *discovers*. They don't stop access.

Some groups are as good as root: `docker`, `libvirt`, `lxd`, and passwordless `sudo`. An account in any of them can read every other account's files and every local VM's disk. Check the Implementer's account with `id -nG` and `sudo -n true`. The second must fail.

Choose the first option that fits:

1. **The Investigator works on a different machine.** The Implementer's account has no login there. The gatekeeper copies each approved spec file across by hand and records it in `provenance/wall-log.md`. This is the simplest wall to defend.
2. **The Implementer runs sandboxed.** Claude Code runs in a container with only `implementation/` and the approved `spec/` mounted. It gets no Docker socket, no host home directory, and no REA. The Investigator can stay on the host.
3. **The Investigator gets a separate OS user** on the same machine, with a `0700` home that holds REA, the target, and `investigation/`. This only isolates if the Implementer's account is in none of the root-equivalent groups above. On a typical dev host it is, which rules this option out there.
4. **A separate Claude Code profile only** (next section). This is discovery scoping, not isolation. Use it alone only when nobody will ever need to show the separation held, for example a personal interoperability project.

Whichever you pick, `$STACK_ROOT/healthcheck.sh` must report `clean-room wall: OK` in the Implementer's account. That check fails if REA is installed there or registered in its default Claude profile.

## Investigator profile (hygiene, on top of isolation)

On the Investigator's side, run Claude Code under its own profile. A `CLAUDE_CONFIG_DIR` holds its own settings, hooks, skills, session transcripts, and login; Claude Code's docs state this for each. Combined with the workspace marker, this keeps Investigator sessions out of shared memory and out of the default profile's discovery. It doesn't block file access, which is what the isolation above is for.

1. Mark the workspace once, from `investigator-workspace/`:
   `$STACK_ROOT/scripts/clean-room-investigator.sh --init`.
   The `.clean-room-investigator` marker keeps every session that runs under it
   out of the memweave store, even one started without the separate profile.
   The check runs against the directory at export time, so archive the
   workspace when the project ends, marker included. Never delete or move it.
2. Start every Investigator session with `$STACK_ROOT/scripts/clean-room-investigator.sh`.
   It refuses to run outside a marked workspace and launches `claude` with
   `CLAUDE_CONFIG_DIR=~/.claude-investigator` (override: `CLEAN_ROOM_CONFIG_DIR`).
   The first launch asks for a login, since the profile keeps its own credentials.
   The profile starts without the stack's skills, hooks, and MCP servers. That's
   intended; add only what the Investigator needs.
3. Install REA with `install.sh --no-setup`, or
   `npm install --global --prefix ~/.local rea-agents@<exact version>`.
4. Inside an Investigator session, register REA with the exact version, as REA's
   own docs do. `rea doctor` reports unpinned registrations as stale:
   `claude mcp add --scope user rea -- npx -y rea-agents@<exact version> mcp`.
   User scope is correct here because the user is the Investigator profile.
   `rea setup --client claude_code` also works, if run from that session's shell
   with `CLAUDE_CONFIG_DIR` set. REA writes to `$CLAUDE_CONFIG_DIR/.claude.json`
   and `$CLAUDE_CONFIG_DIR/skills`.
5. Never run `rea setup` or REA's `install.sh` without `--no-setup` from a
   normal shell. Both register REA in the default profile for every project.
6. Confirm: `claude mcp list` in the Investigator session shows `rea`. In the
   Implementer's account it must not, and `$STACK_ROOT/healthcheck.sh` there
   reports `clean-room wall: OK`.

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
- Setup: the Investigator profile above, then `rea doctor` in an Investigator session to confirm the provider (Hopper, Ghidra, or IDA).
- If the separate profile isn't available, the fallback is per-project registration in the default profile: from `investigator-workspace/`, `claude mcp add --scope local rea -- npx -y rea-agents@<exact version> mcp`. Never use `--scope project`; it writes `.mcp.json` into the repo, where it can cross the wall. This fallback still leaves REA's skill (if `rea setup` installed it) and memory on the shared profile. The workspace marker covers memory; delete the skill by hand.
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

- Start from an empty repo. Pre-flight, in the Implementer's account: the isolation option chosen above is in place; `id -nG` shows no `docker`, `libvirt`, or `lxd`, and `sudo -n true` fails (or the Implementer is sandboxed per option 2); `claude mcp list` from the implementation directory doesn't show `rea`; `$STACK_ROOT/healthcheck.sh` reports `clean-room wall: OK`; `investigation/` and the target's binaries can't be read.
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

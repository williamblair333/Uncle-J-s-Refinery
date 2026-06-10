
---
name: fog-of-chess-engine-mode-implementation
description: Implement a new engineMode variant end-to-end in Fog of Chess — types, UCI bridge, adapter, server polling, REST endpoint, and UI panel — following the validator mode pattern.
---

## When to use

When adding a new `engineMode` to the Fog of Chess platform that requires:
- A new UCI score/analysis pipeline
- Server-side game state annotation
- A REST endpoint for per-game analysis
- A new UI panel in `GameEndPhase`
- A new option in the `Lobby` dropdown

## Key steps demonstrated

### 1. Verify handoff claims before starting
Run `/verify-handoff-claims` against the TODO list. Check `types.ts`, `config.ts`, `server.ts`, and `game.ts` to confirm what is actually wired vs. merely declared.

### 2. Orient with jCodeMunch
get_repo_outline          # overall structure
get_file_outline server.ts  # polling loop location
get_file_outline uci.ts     # existing UCI bridge surface
get_file_outline adapter.ts # adapter class methods

### 3. Layer the implementation bottom-up

**types.ts** — add the new mode literal to `EngineMode` union and any new annotation/result types (e.g. `MoveAnnotation`).

**uci.ts** — add score parsing to the `info` line handler; add a `scoredResolve` slot and a new `getBestMoveWithScore()` method that resolves `{ move, score }` instead of just `move`.

**adapter.ts** — add `evaluatePosition(fen, timeMs)` that calls `getBestMoveWithScore` and returns the score; close over the UCI instance.

**server.ts** (four touch-points):
1. Import new annotation type
2. Add tracking maps (e.g. `validatorAnnotations`, `analysisInProgress`) after existing AI tracking constants
3. Add a `GET /api/analysis/:matchID` endpoint before the replay endpoint
4. In the polling loop:
   - Persist annotations before `continue` on ended games
   - Inject the new mode branch before the existing drafting-phase block

**GameEndPhase.tsx** — add `useState` for analysis fetch + `useEffect` to `GET /api/analysis/:matchID`; render a collapsible panel listing annotated moves.

**GameEndPhase.css** — add panel styles (`.analysis-panel`, `.blunder`, `.inaccuracy` highlight classes).

**Lobby.tsx** (two touch-points):
1. Add the new `<option>` to the engine mode `<select>`
2. Conditionally hide depth slider (analysis runs at fixed time) and show the Black join link (both players are human)

### 4. Type-check both workspaces
cd /opt/proj/proj-fog-of-chess && npx tsc --noEmit
cd /opt/proj/proj-fog-of-chess/client && npx tsc --noEmit

### 5. Index changed files
After edits, call `index_file` on every modified file to keep jCodeMunch current.

## Files touched (validator mode reference)
- `src/types.ts` — mode literal + annotation types
- `src/engine/uci.ts` — score parsing + `getBestMoveWithScore`
- `src/engine/adapter.ts` — `evaluatePosition`
- `src/server.ts` — maps, REST endpoint, polling loop branches
- `client/src/components/GameEndPhase.tsx` — analysis panel
- `client/src/components/GameEndPhase.css` — panel styles
- `client/src/components/Lobby.tsx` — mode select + conditional UI

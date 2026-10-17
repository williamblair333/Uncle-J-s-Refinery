---
name: live-preview
description: Use when building something visual step by step — a CAD part, 3D model, diagram, web page, game scene, character, generated image — or when agents act in a game or simulation the user wants to watch, and the user would benefit from seeing each step as it happens ("show me as you build", "live view", "watch it", "let me see it"). Also use when the user asks how far a build got or which step broke it.
---

# live-preview

A live browser view of any build, one picture per step, with the step history beside it.
The Refinery's `live_preview` MCP server (or `just preview` from the stack repo) does the
publishing and serving. The project only has to produce a picture.

## Loop

1. **Name the session.** `project` = repo name, `session` = what's being built
   (`aaa-tray`, `match-07`). Both are slugs: `[A-Za-z0-9][A-Za-z0-9._-]*`.
2. **Render.** Do it the project's own way, into a scratch dir:
   - FreeCAD / Partikus: `QT_QPA_PLATFORM=offscreen` + `view.saveImage(path, w, h, 'White')`
   - Blender: `blender -b file.blend -o //frame -f 1`
   - Web page: a Playwright or DOMShell screenshot
   - Game: the game's own screenshot, or a frame from its bridge mod
   The first image is the hero. Add extra views (top, side) after it.
3. **Publish.** Call `preview_publish(project, session, images=[...], label="lid attached",
   note="why this step")`. Keep the label to a few words. The note carries the reason.
4. **Show.** Once per session, call `preview_watch(project, session)` and give the user the URL.
   It's on 127.0.0.1 and refreshes about once a second.

Without MCP: `just preview publish --project P --session S --label "..." img.png`, then
`just preview watch --project P --session S --open`.

## Rules

- **Only image files:** png, jpg, gif, webp. Anything else is refused by design.
- **Publish after each step that changes what the user would see.** Don't publish on every
  keystroke. Rendering is the slow part.
- **Several agents can publish into one session safely,** because publishes are serialized.
  Put the agent's name in the label (`red: takes bridge`) so the history reads per agent.
- **A failed render is a step too.** Publish the error screenshot, or say plainly that the
  render failed. Never republish the old picture as if it were new.
- Sessions live in `~/.live-preview/<project>/<session>/`. Delete the directory to discard one.

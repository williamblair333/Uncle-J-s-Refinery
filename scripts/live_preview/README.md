# live_preview

A live browser view of anything being built, for any project. Each step is one or more
images plus a label. The page shows the newest images, the full step history, and what
caused each step. It refreshes about once a second.

```
project renders a picture ──> preview_publish / `just preview publish`
                                   │
                ~/.live-preview/<project>/<session>/
                  session.json  trajectory.json  bundles/  current -> newest bundle
                                   │
                preview_watch / `just preview watch` ──> http://127.0.0.1:<port>/index.html
```

## Use

From an agent, use the `live_preview` MCP server:

| Tool | Does |
|---|---|
| `preview_publish(project, session, images, label, note?, command?)` | adds a step |
| `preview_watch(project, session, port?)` | serves the page and returns its URL |
| `preview_stop(project, session)` | stops serving |
| `preview_status(project?, session?)` | latest step of one session, or all sessions |

From a shell, in any directory (`--project` defaults to the directory name):

```bash
just preview publish --session tray --label "lid attached" hero.png top.png
just preview watch --session tray --open
just preview list
```

The `live-preview` global skill tells agents in every project when and how to use it.

## Guarantees

- **Concurrent publishers are safe.** Each session has a lock, so several agents can
  publish into one session without losing steps.
- **Writes are atomic.** The viewer never reads half a file.
- **Inputs are checked.** Only real images are accepted: png/jpg/gif/webp, matched on
  file content, no symlinks, at most 20 MB each.
- **Names are restricted.** Project and session names are slugs and can't escape
  `LIVE_PREVIEW_HOME`.
- **Localhost only.** The page is served on 127.0.0.1 only.
- **Bounded disk use.** Only the newest 300 bundles keep their images (`--keep`). Older
  steps stay in the history as text.

## Provenance

`viewer.py` and `bundle.py` come from [CLI-Anything](https://github.com/HKUDS/CLI-Anything)
(Apache-2.0). `NOTICE` lists what changed. Tests: `just test tests/test_live_preview.py`.

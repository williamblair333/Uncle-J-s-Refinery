# live_preview

Watch a project take shape in your browser. Each step has a label and one or more images, such as a render of a part so far. The page shows the latest images, the history, and what caused each step. It refreshes about once a second.

```
project renders a picture ──> preview_publish / `just preview publish`
                                   │
                ~/.live-preview/<project>/<session>/
                  session.json  trajectory.json  bundles/  current -> newest bundle
                                   │
                preview_watch / `just preview watch` ──> http://127.0.0.1:<port>/index.html
```

## Use

An agent can use the `live_preview` MCP server, which gives it the tools below.

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
- **Writes are atomic.** A file becomes visible to the viewer only when the whole write is ready.
- **Inputs are checked.** Each image must be at most 20 MB. The tool checks the file contents for png/jpg/gif/webp and rejects symlinks, which are shortcuts to other files.
- **Names are restricted.** Project and session names use a format that keeps their files inside `LIVE_PREVIEW_HOME`.
- **Localhost only.** The server listens on 127.0.0.1, so the page is available on the machine running it.
- **Bounded disk use.** Only the newest 300 bundles keep their images (`--keep`). Older
  steps stay in the history as text.

## Provenance

`viewer.py` and `bundle.py` come from [CLI-Anything](https://github.com/HKUDS/CLI-Anything)
(Apache-2.0). `NOTICE` lists what changed. Run the tests with `just test tests/test_live_preview.py`.

# hypit-ai/hypit

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/hypit-ai/hypit
- Stars: 30805 (gh, 2026-11-20)
- Licence: NOASSERTION
- Last commit: 2026-11-20
- Source: top100 · GitHub top 100 (new entry)

Clone any viral video with AI agents. Not just a script, the whole workflow: swap the face, the words, the B-roll, ship 100 variants in one command, and get your 100M views.

## Take

Uncle J can generate raw clips through ComfyUI, but it has no tool that lets an agent write and compile a whole edited video with captions, B-roll, motion graphics and effects.

Hypit gives an agent a markup language plus a compiler, built on ffmpeg, that turns a script into a finished video, with edits anchored to words rather than timestamps. The README says generation models are optional, so captions and code-drawn visuals can render locally, and it could sit behind make_video as a script or CLI without taking over the runtime. It's pitched at cloning viral videos and face swapping, which isn't what Bill is after, so its value here is only the compositing engine.

Risk: The render step may rely on a headless browser like Playwright or on a hosted Hypit service or model downloads that the excerpt doesn't show, and either would fail the fit test, so check its dependencies and network calls before adopting it.

Scores: tokens 3/5, accuracy 2/5, creativity 4/5, offline 3/5

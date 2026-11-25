# tomasz-tomczyk/crit

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/tomasz-tomczyk/crit
- Stars: 1352 (gh, 2026-11-23)
- Licence: MIT
- Last commit: 2026-11-21
- Source: discovered · Code review and verification (covered)

Review AI coding agents' plans, diffs and running apps in the browser. Local-first, works with any agent.

## Take

Uncle J has no human-in-the-loop review surface: William can't point at a line in a plan, diff or running app and send that comment back to the agent as structured feedback.

Crit is a single local binary that opens plans, git diffs, HTML files, Excalidraw drawings or a proxied dev server in the browser. William can leave comments pinned to a line, and the agent reads those comments and loops until he approves. It complements the existing review skills (judge, adversarial-review, referee), which are all model-reviews-model, by making William's own review faster and more exact. The rival code-review-graph mostly duplicates jcodemunch's blast-radius and risk tools.

Risk: The Claude Code plugin install may add its own slash commands and hooks that overlap the harness's own, so wire in the binary as a script rather than taking the plugin wholesale; also check that the app-proxy mode pulls in no Microsoft browser tooling.

Scores: tokens 3/5, accuracy 4/5, creativity 3/5, offline 5/5

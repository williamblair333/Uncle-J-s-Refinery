# gnana997/crucible

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/gnana997/crucible
- Stars: 2 (gh, 2026-11-27)
- Licence: Apache-2.0
- Last commit: 2026-09-08
- Source: discovered · Sandboxed code execution (blank)

Sandbox runtime for AI coding agents. Firecracker microVMs, a single Go binary, snapshot/fork as first-class primitives.

## Take

Uncle J has no isolated place to run untrusted or model-written code; today that code would run directly on William's Linux host.

Crucible is a self-hosted sandbox runtime in a single Go binary. Each sandbox is a Firecracker microVM with its own kernel, outbound network blocked by default, and snapshot/fork built in, so an agent can try several approaches in parallel from one warm state. Its CLI (run, cp, shell) is easy to wrap as a script or a thin MCP server, and Uncle J stays the runtime. Tupper is the closer E2B-style match, but it only runs on macOS today, so it misses this Linux host.

Risk: It's pre-1.0, needs KVM and a long-running daemon on the host, and pulls container images from registries unless they're cached or mirrored locally first.

Scores: tokens 3/5, accuracy 4/5, creativity 4/5, offline 4/5

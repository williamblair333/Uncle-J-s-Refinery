# gashel01/sandboxmcp

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/gashel01/sandboxmcp
- Stars: 1 (gh, 2026-11-09)
- Licence: Apache-2.0
- Last commit: 2026-06-22
- Source: discovered · Sandboxed code execution (blank)

Hardened polyglot code sandbox for AI agents — isolated execution with seccomp/namespaces. Python lib · CLI · MCP server · FastAPI.

## Take

Uncle J has no isolated execution tool, so model-generated or third-party code currently runs directly on the host or through ad hoc setups.

sandboxmcp is a Python package with an MCP server and CLI that runs Python, JavaScript and shell with resource limits, default-deny network access and SQLite audit logs. It's the easiest candidate to register alongside the existing MCP servers on Bill's Linux host: Tupper's default backend needs macOS, while Fission needs a Rust build, KVM, root-built images and several services. It gives agents a contained way to test code and inspect untrusted downloads while Uncle J stays the runtime.

Risk: The default process backend is not a strong boundary, so it must be pinned to hardened Docker, and its isolation claims and code auto-fix behavior need testing before anything relies on them.

Scores: tokens 2/5, accuracy 3/5, creativity 2/5, offline 5/5

# exitCodeNihil/qafas-sandbox

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/exitCodeNihil/qafas-sandbox
- Stars: 1 (gh, 2026-10-29)
- Licence: MIT
- Last commit: 2026-10-20
- Source: discovered · Sandboxed code execution (blank)

Fast, secure execution sandbox for LLM coding agents: native/VM/Firecracker tiers, escape detection, traces

## Take

Uncle J has no isolated place to run model-generated or delegated code, so anything agy, heretic or ask_local writes runs straight on the host.

Qafas is a self-hosted sandbox for Linux with native, VM and Firecracker tiers. It denies network by default and only allows what you list, keeps the agent and its API keys outside the box, and logs every process, file and network call. It ships packages for Bill's distro family, says it can run air-gapped, and its sbx CLI and HTTP API could be wrapped as a script or a small MCP server, so Uncle J stays the runtime. Tupper only runs on macOS today, and Fission's MCP adapter is promising but its README is thin.

Risk: It's alpha and brings a long-running control plane, a worker daemon and a large guest image. The README doesn't mention an MCP server, so Bill would have to write and maintain that wrapper himself.

Scores: tokens 3/5, accuracy 4/5, creativity 3/5, offline 5/5

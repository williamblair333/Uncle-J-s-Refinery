# lemonlyue/code-sandbox-mcp

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/lemonlyue/code-sandbox-mcp
- Stars: 1 (gh, 2026-10-19)
- Licence: none
- Last commit: 2025-11-16
- Source: discovered · Sandboxed code execution (blank)

MCP server is used to create a secure code sandbox environment, execute code in Docker containers, and provide code execution capabilities for AI applications.

## Take

Uncle J has no MCP tool for running model-generated code in isolation, so answers that depend on code behaviour can't be checked by actually running it.

It's a small Go MCP server with a single tool, execute_code_in_sandbox, that runs Python, PHP or Go inside Docker containers with CPU, memory and disk limits set in a YAML config. It's the easiest candidate to register next to the existing MCP servers on Bill's Linux host. It runs fully locally once the images are pulled. Tupper needs macOS 26 for now. Qafas and Fission bring control planes and Firecracker/KVM orchestration, which is far more to run for a single-user harness.

Risk: Docker containers share the host kernel, and the README doesn't say whether network access is off by default. Treat it as an accuracy aid rather than a security boundary, and confirm egress is disabled in config before trusting it with untrusted code.

Scores: tokens 4/5, accuracy 4/5, creativity 2/5, offline 4/5

# Gemini CLI Integration (Passive Observer)

This package enables native, automatic support for **Gemini CLI** within Uncle J's Refinery. It allows Gemini to leverage the Refinery's structural retrieval, long-term memory, and dreaming playbooks with functional parity to Claude Code.

## Philosophy: Passive Observer
To ensure absolute stability, this integration follows a "Passive Observer" pattern. Gemini CLI reads the Refinery's state and playbooks but **never** modifies Claude Code's internal configuration (`settings.json`) or hook state. All Gemini-specific logic is stored in the project's `GEMINI.md` file.

## Features
- **Structural Parity**: Gemini is mandated to use `jcodemunch-mcp` and `memweave` (`mw_search.py`) for all repository tasks.
- **Context Sync**: A `startup-probe.sh` script allows Gemini to "catch up" on what Claude Code has learned or changed since the last session.
- **Output Discipline**: Enforces the `jOutputMunch` high-signal response style.
- **Zero Interference**: Safe to run alongside Claude Code in the same workspace.

## Installation
The main Refinery installer will prompt you to enable this integration. To install manually:

```bash
bash features/gemini-integration/install.sh
```

## Uninstallation
To remove the Gemini-specific mandates and restore standard Gemini CLI behavior:

```bash
bash features/gemini-integration/install.sh --uninstall
```

## How it Works
The installer injects a block of operational mandates into the project's `GEMINI.md`. Gemini CLI reads this file at the start of every session and adjusts its internal behavior to match the Refinery's methodology.

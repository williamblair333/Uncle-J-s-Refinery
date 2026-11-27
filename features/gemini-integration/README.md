# Gemini CLI Integration (Passive Observer)

Gemini CLI can use the same Refinery resources as Claude Code. It can look up code by structure, search memory from past sessions, and read playbooks that capture steps that worked before.

## Philosophy: Passive Observer
Gemini CLI reads the Refinery's state and playbooks but **never** changes Claude Code's settings (`settings.json`) or the state its hooks use. Hooks are scripts that run automatically at set points in a session. Everything Gemini-specific lives in the project's `GEMINI.md`.

## Features
- Gemini is instructed to use `jcodemunch-mcp` to look up code and `memweave` (`mw_search.py`) to search memory for every repository task.
- The `startup-probe.sh` script helps Gemini catch up on what Claude Code learned or changed since the last session.
- Gemini follows the `jOutputMunch` response style to keep answers focused.
- It's safe to run Gemini alongside Claude Code in the same workspace; neither gets in the other's way.

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
The installer adds the Refinery's instructions to the project's `GEMINI.md`. Gemini CLI reads the file at the start of each session and uses those instructions to decide how to work in the project.

# mohitbadwal/ringback

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/mohitbadwal/ringback
- Stars: 28 (gh, 2026-10-31)
- Licence: Apache-2.0
- Last commit: 2026-06-23
- Source: discovered · Voice and wake word (blank)

Let your AI agent call your phone and talk to you — MCP servers for live, interruptible voice calls + tiered alerts, using free self-hosted pieces (pjsua2 + whisper.cpp + Linphone). No paid telephony, no extra API key.

## Take

Uncle J can speak (speak/Chatterbox) and message over Telegram, but it can't start a live, two-way voice conversation where Bill can interrupt, and it has no escalating alerts for urgent failures.

It ships two MCP servers. ringback-alert sends tiered push or SIP-ring alerts. ringback-voice runs phone calls with barge-in, using pjsua2, whisper.cpp and Piper. The model already driving the session is the voice on the line, so Uncle J stays the runtime and no extra LLM key or per-minute billing is needed. It runs headless on Linux and fits next to the existing healthcheck and stack-alert scripts as a stronger escalation path. The other four candidates fit worse: local-stt-mcp is tuned for Apple Silicon and only transcribes, and the rest are standalone assistants that would take over the runtime.

Risk: Calls depend on an outside SIP provider and a native pjsua2 build or Docker image, so they aren't fully offline. A tool that lets the model decide to ring Bill's phone also needs tight rules on when it may call.

Scores: tokens 3/5, accuracy 3/5, creativity 4/5, offline 3/5

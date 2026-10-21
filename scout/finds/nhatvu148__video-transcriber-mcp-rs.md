# nhatvu148/video-transcriber-mcp-rs

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/nhatvu148/video-transcriber-mcp-rs
- Stars: 19 (gh, 2026-10-20)
- Licence: Apache-2.0
- Last commit: 2026-10-04
- Source: discovered · Voice and wake word (blank)

High-performance MCP server for transcribing videos from 1000+ platforms using whisper.cpp

## Take

Uncle J has no speech-to-text path, so audio and video can't reach the stack unless someone pastes a transcript in by hand.

It's a single-binary Rust MCP server that runs whisper.cpp offline and transcribes local video files or links fetched with yt-dlp. It runs over stdio on Linux x86_64 and needs no Python or Node, so it slots in next to the other MCP servers without taking over the runtime. It feeds the existing media-teardown skill directly, and the voice-and-wake-word alternatives are either macOS-tuned (local-stt-mcp), dependent on a SIP account (ringback) or full assistant runtimes.

Risk: Whole transcripts landing in context can burn tokens fast unless output goes to a file and is skimmed through ask_local or jdocmunch, and URL fetching depends on yt-dlp keeping up with platform changes.

Scores: tokens 2/5, accuracy 4/5, creativity 3/5, offline 4/5

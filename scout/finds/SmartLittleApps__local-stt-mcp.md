# SmartLittleApps/local-stt-mcp

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/SmartLittleApps/local-stt-mcp
- Stars: 20 (gh, 2026-11-11)
- Licence: MIT
- Last commit: 2025-06-03
- Source: discovered · Voice and wake word (blank)

A high-performance Model Context Protocol (MCP) server providing local speech-to-text transcription using whisper.cpp, optimized for Apple Silicon.

## Take

Uncle J can already speak through the delegate  tool and speech.sh, but it has no local MCP tool that turns audio files into text.

It's a small TypeScript MCP server that wraps whisper.cpp and exposes transcribe, transcribe_long and transcribe_with_speakers. Output comes back as txt, json, vtt or srt, and ffmpeg converts other audio formats first. It plugs in next to the other MCP servers, so Uncle J stays the runtime and transcripts reach Claude as compact text instead of raw audio. The other candidates are full assistants that take over the runtime (JARVIS, t2yLLM) or need specific hardware (RK3576). The Vietnamese assistant is a standalone app.

Risk: It's tuned for Apple Silicon and its setup assumes Homebrew, so on Bill's Linux box whisper.cpp and the model download may need manual work and won't get the speed it advertises. Speaker diarization also needs a HuggingFace token and a pyannote licence, which goes against fully offline use.

Scores: tokens 4/5, accuracy 3/5, creativity 2/5, offline 4/5

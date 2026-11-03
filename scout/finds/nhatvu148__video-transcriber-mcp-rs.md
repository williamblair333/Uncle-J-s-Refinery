# nhatvu148/video-transcriber-mcp-rs

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/nhatvu148/video-transcriber-mcp-rs
- Stars: 19 (gh, 2026-11-02)
- Licence: Apache-2.0
- Last commit: 2026-11-01
- Source: watchlist

High-performance MCP server for transcribing videos from 1000+ platforms using whisper.cpp

## Take

Uncle J has no speech-to-text path: delegate covers TTS, images and video generation, and media-teardown needs a transcript but has nothing that can produce one from a video URL or local file.

This is a Rust MCP server that uses whisper.cpp to transcribe local video files, or videos fetched with yt-dlp, into TXT, JSON or Markdown. It runs over stdio as a standalone binary with no Python or Node runtime. It would feed media-teardown directly and keep transcription on-box, which suits the offline and privacy goals. Register just the binary and skip the bundled plugin's /transcribe skill so Uncle J's own skill routing stays in charge.

Risk: Whisper's medium and large models will compete with ComfyUI and llama-server for the GPU, yt-dlp breaks often as sites change, and long transcripts are untrusted text that can flood the context unless the server writes them to a file.

Scores: tokens 3/5, accuracy 3/5, creativity 3/5, offline 4/5

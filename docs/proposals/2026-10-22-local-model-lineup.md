# Local model lineup: fewest models, every goal (2026-10-22)

**Status:** decided by Bill, not started. He prioritizes it later.
**Goal:** cover text, image understanding, image generation, video, speech-to-text and
cloned-voice speech on this host (RTX 3060 12 GB, 46 GB RAM) with as few models and GPU
users as possible. Commercial use must be allowed.

## Decisions

- **Licenses:** revenue-capped licenses are fine until Bill makes $5M+ a year; swap models
  then. FLUX.3 Klein caps at $5M, LTX-2 at $10M. Apache and MIT have no cap.
- **Cloned voices:** wanted.
- **lc0:** can be stopped whenever a model needs the GPU.
- **Ollama goes.** Nothing needs it once Heretic covers text.

## Lineup

| # | Job | Model | License | Runtime | GPU |
|---|---|---|---|---|---|
| 1 | Text, reasoning, code, reading images | Qwen3.6-35B-A3B Heretic (running, PR #165) | Apache 2.0 | llama-server | 4.8 GB awake, 0 asleep |
| 2 | Image generation | Z-Image-Turbo (Apache), or FLUX.3 Klein (Kommunity, < $5M) | see left | ComfyUI | most of 12 GB |
| 3 | Video | Wan 2.2 (Apache); LTX-2.x (< $10M) if sound is wanted | see left | ComfyUI | all of 12 GB |
| 4 | Speech-to-text | Whisper (whisper.cpp) | MIT | whisper.cpp server | none (CPU) |
| 5 | Speech with cloned voices | Chatterbox (Turbo on GPU, or Nano on CPU) | MIT, output watermarked | its own server | small, or none with Nano |

## Culling

- **Drop #2 if Wan's stills are good enough.** Wan can render single frames. Test it
  side by side with the image pick; if it passes, the lineup is four models.
- **Chatterbox Nano on CPU** takes speech off the GPU entirely; check its quality first.
- **Qwen3-Omni-30B-A3B rejected:** it hears and speaks, but it's a second LLM with no
  voice cloning, and llama.cpp speech output is unverified.
- **Retire qwen3.5:9b, granite4.2:8b and the Ollama container.** First:
  1. ~~Test Heretic prefill with `-b 2048 -ub 2048`.~~ Done: an 18.7k-token prefill went
     from 61 s to 24 s (306 → 775 tok/s) for +0.2 GB VRAM; generation unchanged at ~40 tok/s.
     4096 is faster (17 s) but crowds out lc0. Numbers in `docker/llama-heretic/compose.yaml`.
  2. ~~Move ask_local's backend settings to a host-local file, so a reinstall can't revert
     to Ollama. Doctor flags a mismatch.~~ Done: `config/ask_local.env`, read by the
     server itself; healthcheck `ask_local — settings source` flags a mismatch.
  3. ~~Rework `install.sh`, `healthcheck.sh` and `scripts/ollama-up.sh` around llama-server.~~
     Done on hosts with `config/ask_local.env`: `scripts/ask-local-up.sh` (`just ask-local-up`)
     starts the configured backend, and install.sh calls it. **Still open:** other hosts (Pi,
     tc-vmh-03) have no config and stay on Ollama until a small llama-server model is picked
     for them.
  4. ~~Check whether Sinkpoint's Bannerlord mod accepts an OpenAI-style URL.~~ Yes, per the
     author's "LLM support and configuration" article (Nexus, mountandblade2bannerlord
     articles/1674): `Modules/SpLLM/config.json` picks a `"provider"` from `"providers"`, and
     type `"openai"` POSTs `/chat/completions`. Point it at Heretic (`http://<this host>:8090/v1`,
     model `heretic`) — but llama-heretic binds 127.0.0.1, so a game on another PC needs a LAN
     bind first. The exact URL/model key names are in `config.default.json`; read them when
     the mod is installed (it isn't on this host).
  5. ~~Move partikus off Ollama.~~ Done (partikus #45): backend `"llama"` uses Heretic;
     integration 7/7 in ~49 s. `"ollama"` stays for hosts that still have it.
  6. **Blocker found 2026-10-22: Klarheit.** Its hourly trials (`klarheit-rv`, `klarheit-m12`
     timers) run `qwen3.5:9b` through Ollama, pinned by digest (`src/klarheit/rv/viewer.py`,
     `methods.json` "M11-local"). About 15 calls an hour, 972 in 72 h. Swapping the model breaks
     those trials' protocol, so Ollama and the 9B stay until Klarheit's local arm ends or Bill
     re-registers it on another model. granite4.2:8b is unused and can go now.

## GPU handoff

One GPU job at a time. Heretic already frees its VRAM after 10 idle minutes. Image and
video jobs need lc0 stopped and Heretic asleep; a small wrapper should do both before a
ComfyUI job and say so if it can't.

## Open items

- FLUX.3 Klein came out 2026-10-15; it clears the two-week version rule on 2026-10-29.
  Its best results need a prompt upsampler that wants about 28 GB, which this host lacks.
- ~~Load Heretic's vision file (`--mmproj`) when image input is needed.~~ Loaded on CPU
  (`--no-mmproj-offload`): no VRAM, 42 s per first image. Numbers in the compose file.
- Let ask_local ask for thinking per call; the word-problem test ran out of tokens with it off.

#!/usr/bin/env bash
# `just whisper <compose args>` and `just tts <compose args>`: the local speech services.
#   whisper → docker/whisper/compose.yaml    (whisper.cpp speech-to-text, 127.0.0.1:8092)
#   tts     → docker/chatterbox/compose.yaml (Chatterbox Nano cloned-voice TTS, 127.0.0.1:8093)
# `up` goes through dcup when it's installed, so the port is claimed in the Docker port
# registry; every other subcommand (down, logs, ps, build, …) is plain `docker compose`.
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "${1:-}" in
    whisper) COMPOSE="$PROJ_ROOT/docker/whisper/compose.yaml" ;;
    tts)     COMPOSE="$PROJ_ROOT/docker/chatterbox/compose.yaml" ;;
    *) echo "usage: speech.sh whisper|tts <docker compose args>" >&2; exit 2 ;;
esac
shift

DCUP="$(command -v dcup || true)"
DCUP_FALLBACK="${DCUP_FALLBACK:-/opt/lib/docker-port-registry/dcup}"
[[ -n "$DCUP" || ! -x "$DCUP_FALLBACK" ]] || DCUP="$DCUP_FALLBACK"

if [[ "${1:-}" == up && -n "$DCUP" ]]; then
    shift
    exec "$DCUP" up -f "$COMPOSE" "$@"
fi
exec docker compose -f "$COMPOSE" "$@"

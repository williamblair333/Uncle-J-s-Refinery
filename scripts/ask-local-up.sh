#!/usr/bin/env bash
# Start the backend this host's ask_local uses. The backend comes from the same place
# scripts/ask_local/server.py reads it: process env, then config/ask_local.env
# (ASK_LOCAL_CONFIG moves it, empty disables), then the default.
#   openai → llama-heretic (docker/llama-heretic/compose.yaml), through dcup when installed
#   ollama → scripts/ollama-up.sh, with the configured URL and model exported
# Idempotent: safe to re-run from install.sh or a healthcheck hint. Never downloads a GGUF.
#
# Exit codes: 0 = backend answering, 1 = docker missing / bad backend / model missing / down.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG="${ASK_LOCAL_CONFIG-$PROJ_ROOT/config/ask_local.env}"

# Env first, then the file (last line wins), then the default. The file is read, never sourced.
setting() {
    local v="${!1:-}"
    if [[ -z "$v" && -n "$CONFIG" && -f "$CONFIG" ]]; then
        v="$(grep -E "^[[:space:]]*$1[[:space:]]*=" "$CONFIG" | tail -1 | cut -d= -f2- \
            | sed -E "s/^[[:space:]]*//; s/[[:space:]]*\$//; s/^[\"']//; s/[\"']\$//")" || true
    fi
    printf '%s' "${v:-$2}"
}

backend="$(setting ASK_LOCAL_BACKEND ollama)"
case "$backend" in
    ollama)
        ASK_LOCAL_URL="$(setting ASK_LOCAL_URL http://127.0.0.1:11434)"
        ASK_LOCAL_MODEL="$(setting ASK_LOCAL_MODEL qwen3.5:9b)"
        export ASK_LOCAL_URL ASK_LOCAL_MODEL
        exec bash "$SCRIPT_DIR/ollama-up.sh"
        ;;
    openai) ;;
    *)
        echo "ask-local-up: ASK_LOCAL_BACKEND=$backend is not ollama or openai (${CONFIG:-env})" >&2
        exit 1
        ;;
esac

URL="$(setting ASK_LOCAL_URL http://127.0.0.1:8090)"
COMPOSE="$PROJ_ROOT/docker/llama-heretic/compose.yaml"

if ! command -v docker >/dev/null 2>&1; then
    echo "ask-local-up: docker is not installed" >&2
    exit 1
fi

# The compose file mounts the model dir at /models; read it from there, not a second copy.
models="$(sed -nE 's#^[[:space:]]*- (/[^:]+):/models.*#\1#p' "$COMPOSE" | head -1)"
if ! find "$models" -name '*.gguf' -print -quit 2>/dev/null | grep -q .; then
    echo "ask-local-up: no .gguf under $models — download the model named in $COMPOSE first" >&2
    exit 1
fi

# dcup claims heretic's port in the port registry; it isn't always on PATH.
DCUP="$(command -v dcup || true)"
DCUP_FALLBACK="${DCUP_FALLBACK:-/opt/lib/docker-port-registry/dcup}"
[[ -n "$DCUP" || ! -x "$DCUP_FALLBACK" ]] || DCUP="$DCUP_FALLBACK"
if [[ -n "$DCUP" ]]; then
    "$DCUP" up -f "$COMPOSE" -d
else
    docker compose -f "$COMPOSE" up -d
fi

# Loading the model takes a while on a cold start; /health answers 200 once it can serve.
for _ in $(seq 1 60); do
    curl -sf --max-time 2 "$URL/health" >/dev/null 2>&1 && break
    sleep 3
done
if ! curl -sf --max-time 2 "$URL/health" >/dev/null 2>&1; then
    echo "ask-local-up: $URL/health not answering after 180 s — check: docker logs llama-heretic" >&2
    exit 1
fi
echo "ask-local-up: llama-heretic ready at $URL"

#!/usr/bin/env bash
# Start the Ollama backend for ask_local and make sure the default model is pulled.
# Idempotent: safe to re-run from install.sh or a healthcheck hint.
#
# Compose file: a host-managed /opt/docker/ollama/compose.yaml wins when present (the
# original host keeps its own there). Otherwise the repo's docker/ollama/compose.yaml,
# plus compose.gpu.yaml when Docker has the nvidia runtime.
#
# Exit codes: 0 = API up and model present, 1 = docker missing / API down / pull failed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
URL="${ASK_LOCAL_URL:-http://127.0.0.1:11434}"
MODEL="${ASK_LOCAL_MODEL:-qwen3.5:9b}"
HOST_COMPOSE=/opt/docker/ollama/compose.yaml

if ! command -v docker >/dev/null 2>&1; then
    echo "ollama-up: docker is not installed" >&2
    exit 1
fi

if [[ -f "$HOST_COMPOSE" ]]; then
    files=(-f "$HOST_COMPOSE")
else
    files=(-f "$PROJ_ROOT/docker/ollama/compose.yaml")
    if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q '"nvidia"'; then
        files+=(-f "$PROJ_ROOT/docker/ollama/compose.gpu.yaml")
        echo "ollama-up: nvidia runtime found — GPU overlay applied"
    else
        echo "ollama-up: no nvidia runtime — running on CPU (expect ~60 s+ per call)"
    fi
    # Create the bind-mount source as this user; docker would create it root-owned.
    # Same fallback order every run, so the models dir is stable across invocations.
    if [[ -z "${OLLAMA_MODELS_DIR:-}" ]]; then
        OLLAMA_MODELS_DIR=/opt/models/ollama
        mkdir -p "$OLLAMA_MODELS_DIR" 2>/dev/null || OLLAMA_MODELS_DIR="$HOME/.local/share/ollama-models"
    fi
    mkdir -p "$OLLAMA_MODELS_DIR"
    export OLLAMA_MODELS_DIR
    echo "ollama-up: models dir $OLLAMA_MODELS_DIR"
fi

docker compose "${files[@]}" up -d

# The API answers only after startup/GPU discovery (~5 s measured with a GPU).
for _ in $(seq 1 30); do
    curl -sf --max-time 2 "$URL/api/version" >/dev/null 2>&1 && break
    sleep 1
done
if ! curl -sf --max-time 2 "$URL/api/version" >/dev/null 2>&1; then
    echo "ollama-up: API not answering at $URL after 30 s — check: docker logs ollama" >&2
    exit 1
fi

if curl -sf --max-time 5 "$URL/api/tags" | grep -qF "\"name\":\"$MODEL\""; then
    echo "ollama-up: model $MODEL already present"
else
    echo "ollama-up: pulling $MODEL (several GB, first run only)"
    docker exec ollama ollama pull "$MODEL"
fi
echo "ollama-up: ready at $URL"

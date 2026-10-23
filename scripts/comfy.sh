#!/usr/bin/env bash
# `just comfy <compose args>` for docker/comfyui/compose.yaml.
# `up` goes through dcup when it's installed, so port 8188 is claimed in the Docker port
# registry; every other subcommand (down, logs, build, ps, …) is plain `docker compose`.
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="$PROJ_ROOT/docker/comfyui/compose.yaml"
OUTPUTS="${COMFY_OUTPUTS:-/opt/outputs/comfyui}"

DCUP="$(command -v dcup || true)"
DCUP_FALLBACK="${DCUP_FALLBACK:-/opt/lib/docker-port-registry/dcup}"
[[ -n "$DCUP" || ! -x "$DCUP_FALLBACK" ]] || DCUP="$DCUP_FALLBACK"

if [[ "${1:-}" == up ]]; then
    # Docker would create a missing bind source as root; make it as the user first.
    mkdir -p "$OUTPUTS"
    if [[ -n "$DCUP" ]]; then
        shift
        exec "$DCUP" up -f "$COMPOSE" "$@"
    fi
fi
exec docker compose -f "$COMPOSE" "$@"

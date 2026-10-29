#!/usr/bin/env bash
# `just heretic <compose args>` for docker/llama-heretic/compose.yaml.
# `up` goes through dcup when it's installed, so port 8090 is claimed in the Docker port
# registry (the chat page's Start and ask-local-up.sh do the same); every other
# subcommand (down, logs, ps, …) is plain `docker compose`.
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="$PROJ_ROOT/docker/llama-heretic/compose.yaml"

# `just gpu mtw2` writes state/gpu-mode; every `up` honours it (scripts/gpu-mode.sh)
if [[ "$(cat "$PROJ_ROOT/state/gpu-mode" 2>/dev/null)" == mtw2 ]]; then
    export HERETIC_FIT="${HERETIC_FIT:-1024}" HERETIC_CTX="${HERETIC_CTX:-65536}" HERETIC_NP="${HERETIC_NP:-2}"
fi

DCUP="$(command -v dcup || true)"
DCUP_FALLBACK="${DCUP_FALLBACK:-/opt/lib/docker-port-registry/dcup}"
[[ -n "$DCUP" || ! -x "$DCUP_FALLBACK" ]] || DCUP="$DCUP_FALLBACK"

if [[ "${1:-}" == up && -n "$DCUP" ]]; then
    shift
    exec "$DCUP" up -f "$COMPOSE" "$@"
fi
exec docker compose -f "$COMPOSE" "$@"

#!/usr/bin/env bash
# `just small <compose args>` for docker/llama-small/compose.yaml (CPU model for the Pi / tc-vmh-03).
# `up` goes through dcup when it's installed, so its port is claimed in the Docker port
# registry; every other subcommand (down, logs, ps, …) is plain `docker compose`.
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="$PROJ_ROOT/docker/llama-small/compose.yaml"

DCUP="$(command -v dcup || true)"
DCUP_FALLBACK="${DCUP_FALLBACK:-/opt/lib/docker-port-registry/dcup}"
[[ -n "$DCUP" || ! -x "$DCUP_FALLBACK" ]] || DCUP="$DCUP_FALLBACK"

if [[ "${1:-}" == up && -n "$DCUP" ]]; then
    shift
    exec "$DCUP" up -f "$COMPOSE" "$@"
fi
exec docker compose -f "$COMPOSE" "$@"

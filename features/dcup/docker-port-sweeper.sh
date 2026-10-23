#!/usr/bin/env bash
# docker-port-sweeper.sh — updates last_seen_running timestamps in the port
# registry when containers start. NOT on the correctness path — correctness
# is handled by dcup's inline reconcile. This is liveness display only.
# Registry dir resolves the same way dcup does (see features/dcup/dcup).

if [[ -n "${DCUP_REGISTRY_DIR:-}" ]]; then
  REGISTRY_DIR="$DCUP_REGISTRY_DIR"
elif [[ -d /opt/lib/docker-port-registry ]]; then
  REGISTRY_DIR=/opt/lib/docker-port-registry
else
  REGISTRY_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/dcup"
fi
DB="${REGISTRY_DIR}/ports.db"
REAL_DOCKER="${DOCKER_BIN:-$(command -v docker || echo /usr/bin/docker)}"

[[ -f "$DB" ]] || { echo "sweeper: no DB at $DB, waiting..." >&2; sleep 10; exit 1; }

echo "docker-port-sweeper: listening for container start events..."

"$REAL_DOCKER" events \
  --filter type=container \
  --filter event=start \
  --format '{{.Actor.ID}} {{index .Actor.Attributes "com.docker.compose.project"}}' \
| while read -r cid project; do
  [[ -z "$project" ]] && continue
  now="$(date -Iseconds)"
  sqlite3 "$DB" \
    "UPDATE port_claims SET last_seen_running='${now}' WHERE project='$(echo "$project" | sed "s/'/''/g")';" \
    2>/dev/null || true
  echo "sweeper: updated last_seen for $project ($cid)"
done

#!/usr/bin/env bash
# Remind to revisit the local 125B agent model once this machine has the RAM for it.
# Shelved 2026-11-04 at 46 GB (only an IQ1_M fit); see docs/research-later.md.
# Prints one line when MemTotal >= RAM_REVISIT_GIB (default 120 GiB: a 128 GB box
# reports ~125), nothing otherwise. Always exits 0 — it runs inside healthcheck.sh,
# and a missing /proc/meminfo (Windows port) or bad input must never fail that.
# Once the 125B has been benched, delete this script and check_ram_revisit.
MEMINFO="${RAM_REVISIT_MEMINFO:-/proc/meminfo}"
THRESHOLD="${RAM_REVISIT_GIB:-120}"
[[ "$THRESHOLD" =~ ^[0-9]+$ ]] || exit 0
[[ -r "$MEMINFO" ]] || exit 0
kib=$(awk '/^MemTotal:/ {print $2; exit}' "$MEMINFO" 2>/dev/null)
[[ "$kib" =~ ^[0-9]+$ ]] || exit 0
gib=$(( kib / 1048576 ))
if (( gib >= THRESHOLD )); then
    echo "RAM is now ${gib} GiB: time to revisit the local 125B model (docs/research-later.md); delete scripts/ram_revisit.sh once benched"
fi
exit 0

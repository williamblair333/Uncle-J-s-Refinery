#!/usr/bin/env bash
# `just comfy-models`: fetch the ComfyUI models listed in docker/comfyui/models.txt
# into $MODELS_ROOT (default /opt/models) and check each one's sha256.
#
# The expected sha256 comes from the Git LFS pointer at the same pinned commit
# (<url> with /resolve/ → /raw/, line "oid sha256:<hex>"). The commit hash covers the pointer.
# A file already in place is hashed, not re-downloaded. A download goes to <dest>.part
# (resumable with curl -C -) and is renamed only after its hash matches, so a file at
# <dest> is always a verified one. A mismatch leaves <dest>.part.bad and exits 1.
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="${COMFY_MODELS_MANIFEST:-$PROJ_ROOT/docker/comfyui/models.txt}"
MODELS_ROOT="${MODELS_ROOT:-/opt/models}"
FILTER="${1:-}"   # optional substring: `just comfy-models wan2.2`

expected_sha() {  # $1 = resolve URL → sha256 from the LFS pointer, or empty
    curl -fsSL --retry 3 "${1/\/resolve\//\/raw\/}" </dev/null \
        | sed -n 's/^oid sha256:\([0-9a-f]\{64\}\)$/\1/p' | head -n1
}

fail=0
while read -r dest url extra; do
    [[ -z "$dest" || "$dest" == \#* ]] && continue
    [[ -n "$FILTER" && "$dest" != *"$FILTER"* ]] && continue
    if [[ -z "$url" || -n "${extra:-}" || "$url" != */resolve/* ]]; then
        echo "bad manifest line: $dest" >&2; fail=1; continue
    fi
    sha="$(expected_sha "$url" || true)"
    if [[ ! "$sha" =~ ^[0-9a-f]{64}$ ]]; then
        echo "NO-HASH  $dest (no LFS pointer at ${url/\/resolve\//\/raw\/})" >&2
        fail=1; continue
    fi
    target="$MODELS_ROOT/$dest"
    if [[ -f "$target" ]]; then
        if [[ "$(sha256sum "$target" | cut -d' ' -f1)" == "$sha" ]]; then
            echo "ok       $dest"; continue
        fi
        echo "MISMATCH $dest (in place; left alone, move it aside to re-fetch)" >&2
        fail=1; continue
    fi
    mkdir -p "$(dirname "$target")"
    echo "fetch    $dest"
    curl -fL --retry 5 --retry-delay 10 -C - -o "$target.part" "$url" </dev/null
    if [[ "$(sha256sum "$target.part" | cut -d' ' -f1)" == "$sha" ]]; then
        mv "$target.part" "$target"
        echo "ok       $dest"
    else
        mv "$target.part" "$target.part.bad"
        echo "MISMATCH $dest (download kept as $target.part.bad)" >&2
        fail=1
    fi
done < "$MANIFEST"
exit "$fail"

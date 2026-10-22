#!/usr/bin/env bash
# build-vendored-pysqlite3.sh — build the pysqlite3 wheel against SQLite 3.51.3 ONCE,
# vendored into the repo so `uv sync` stops reverting to the PyPI 3.51.1 wheel.
#
# WHY: SQLite <3.51.3 carries a WAL-reset data-race bug (present since 3.7.0, 2010).
# The PyPI pysqlite3 wheel bundles 3.51.1 — still affected. install.sh §2b builds
# 3.51.3 from source into the venv, but a bare `uv sync` reinstalls the PyPI wheel
# and silently reintroduces the bug. Vendoring a path-pinned 3.51.3 wheel (referenced
# from pyproject.toml [tool.uv.sources]) makes `uv sync` install the FIXED wheel.
#
# WHY A MANYLINUX CONTAINER: a wheel built on the host links against the host's
# glibc. The first vendored wheel was built on a glibc-2.41 host, needed glibc
# >= 2.33, and would not import on Debian 11 (glibc 2.31). Building inside
# manylinux2014 (glibc 2.17) and running `auditwheel repair` gives a wheel tagged
# manylinux_2_17 that imports on any glibc >= 2.17.
#
# Needs Docker. Run it yourself (it compiles C):
#   ! bash scripts/build-vendored-pysqlite3.sh
#
# It then verifies the wheel imports and reports SQLite 3.51.3 inside a Debian 11
# (bullseye) Python container. On success, point pyproject.toml [tool.uv.sources]
# at the printed filename, then `uv lock` + `uv sync --inexact`.
set -euo pipefail

PYSQLITE_VERSION="0.6.0"
SQLITE_AMALG_URL="https://www.sqlite.org/2026/sqlite-amalgamation-3510300.zip"
SQLITE_EXPECTED="3.51.3"
PYTAG="${PYTAG:-cp311}"
PYVER="${PYVER:-3.11}"
BUILD_IMAGE="${BUILD_IMAGE:-quay.io/pypa/manylinux2014_x86_64}"
PLAT="${PLAT:-manylinux2014_x86_64}"
VERIFY_IMAGE="${VERIFY_IMAGE:-python:${PYVER}-slim-bullseye}"

# ── inside the build container ──────────────────────────────────────────────
if [ "${1:-}" = "--in-container" ]; then
    OUT="/out"
    PY="/opt/python/${PYTAG}-${PYTAG}/bin/python"
    TMP_SRC="$(mktemp -d)"
    echo "==> fetching SQLite amalgamation"
    curl -sSL --fail "$SQLITE_AMALG_URL" -o "$TMP_SRC/amalg.zip"
    unzip -q -j "$TMP_SRC/amalg.zip" "*/sqlite3.c" "*/sqlite3.h" -d "$TMP_SRC/"
    echo "==> fetching pysqlite3 $PYSQLITE_VERSION sdist"
    _SDIST_URL="$(curl -sSL --fail "https://pypi.org/pypi/pysqlite3/$PYSQLITE_VERSION/json" \
        | "$PY" -c "import sys,json;print(next(u['url'] for u in json.load(sys.stdin)['urls'] if u['packagetype']=='sdist'))")"
    curl -sSL --fail "$_SDIST_URL" -o "$TMP_SRC/pysqlite3.tar.gz"
    tar xz -C "$TMP_SRC" -f "$TMP_SRC/pysqlite3.tar.gz"
    SRC_DIR="$TMP_SRC/pysqlite3-$PYSQLITE_VERSION"
    cp "$TMP_SRC/sqlite3.c" "$TMP_SRC/sqlite3.h" "$SRC_DIR/"
    echo "==> building wheel with $PY (statically links the $SQLITE_EXPECTED amalgamation)"
    ( cd "$SRC_DIR" && "$PY" -m pip wheel --no-deps -w "$TMP_SRC/raw" . )
    echo "==> auditwheel repair --plat $PLAT"
    auditwheel repair --plat "$PLAT" -w "$OUT" "$TMP_SRC"/raw/pysqlite3-*.whl
    auditwheel show "$OUT"/pysqlite3-"$PYSQLITE_VERSION"-"$PYTAG"-*manylinux*.whl
    exit 0
fi

# ── on the host ─────────────────────────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$REPO_ROOT/vendor/wheels"
command -v docker >/dev/null 2>&1 || { echo "FATAL: docker not found" >&2; exit 1; }

OUT_DIR="$(mktemp -d)"
trap 'rm -rf "$OUT_DIR"' EXIT
chmod 777 "$OUT_DIR"

echo "==> building pysqlite3 $PYSQLITE_VERSION (SQLite $SQLITE_EXPECTED) for $PYTAG in $BUILD_IMAGE"
docker run --rm \
    -e PYTAG="$PYTAG" -e PLAT="$PLAT" \
    -v "$REPO_ROOT/scripts/build-vendored-pysqlite3.sh:/build.sh:ro" \
    -v "$OUT_DIR:/out" \
    "$BUILD_IMAGE" bash /build.sh --in-container

WHEEL="$(ls "$OUT_DIR"/pysqlite3-"$PYSQLITE_VERSION"-"$PYTAG"-*manylinux*.whl 2>/dev/null | head -1)"
[ -f "$WHEEL" ] || { echo "FATAL: no manylinux wheel produced" >&2; exit 1; }
NAME="$(basename "$WHEEL")"

# --- verify on the oldest glibc we promise (Debian 11 / 2.31) -----------------
echo "==> verifying $NAME in $VERIFY_IMAGE"
GOT="$(docker run --rm -v "$OUT_DIR:/w:ro" "$VERIFY_IMAGE" sh -c \
    "ldd --version | head -1 >&2; pip install --quiet --no-index /w/$NAME 2>/dev/null >&2; \
     python -c 'import pysqlite3;print(pysqlite3.sqlite_version)'")"
if [ "$GOT" != "$SQLITE_EXPECTED" ]; then
    echo "FATAL: wheel reports SQLite '$GOT' in $VERIFY_IMAGE, expected $SQLITE_EXPECTED — NOT vendoring" >&2
    exit 1
fi

mkdir -p "$VENDOR_DIR"
cp "$WHEEL" "$VENDOR_DIR/$NAME"
echo
echo "✅ vendored wheel verified: vendor/wheels/$NAME  (SQLite $GOT in $VERIFY_IMAGE)"
echo
echo "NEXT: point pyproject.toml [tool.uv.sources] pysqlite3 at vendor/wheels/$NAME,"
echo "      remove any older wheel there, then: uv lock && uv sync --inexact"
